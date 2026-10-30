"""Polite HTTP client: per-host minimum interval, retries with exponential backoff, optional disk cache.

* No API keys or auth headers are ever sent.
* `immutable=True` marks requests whose answer cannot change (finalized historical blocks, closed months);
  those are served from data/cache/ when present, which makes long fetches resumable without re-hitting servers.
  `max_age_s` reuses a cached answer to a *mutable* request only if it is younger than that (resuming an interrupted
  run on the same day without re-asking). Everything else is always re-downloaded by `make refresh`.
* Shared limits: hosts matching a suffix in `[http.shared_min_interval_s]` (FastNear's RPC, archival and indexer
  hosts) get one request in flight at a time across processes, with that minimum pause between requests (a lock
  file in data/cache/), because FastNear answered HTTP 429 to concurrent requests from one machine.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from . import config, paths


class TransientError(Exception):
    """Retryable failure (429, 5xx, timeouts, overloaded RPC)."""


class RpcError(Exception):
    """Non-retryable JSON-RPC error (e.g. UNKNOWN_BLOCK for a skipped height)."""

    def __init__(self, error: dict[str, Any]):
        self.error = error
        cause = (error.get("cause") or {}).get("name") or error.get("name") or ""
        self.cause = cause
        super().__init__(f"{cause}: {json.dumps(error)[:300]}")


TRANSIENT_RPC_CAUSES = {"TIMEOUT_ERROR", "INTERNAL_ERROR", "NO_SYNCED_BLOCKS", "NOT_SYNCED_YET"}


@dataclass
class HostStats:
    requests: int = 0
    cache_hits: int = 0
    retries: int = 0
    rate_limited: int = 0
    errors: int = 0
    bytes: int = 0


@dataclass
class PoliteClient:
    cache_dir: Path = paths.CACHE
    verbose: bool = True
    stats: dict[str, HostStats] = field(default_factory=lambda: defaultdict(HostStats))
    _last: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        cfg = config.load()["http"]
        self._cfg = cfg
        self._intervals: dict[str, float] = dict(cfg["min_interval_s"])
        self._shared: dict[str, float] = dict(cfg.get("shared_min_interval_s", {}))
        self._client = httpx.Client(
            timeout=cfg["timeout_s"],
            headers={"User-Agent": cfg["user_agent"], "Accept": "application/json"},
            follow_redirects=True,
        )

    # ------------------------------------------------------------------ helpers
    def _throttle(self, host: str) -> None:
        interval = self._intervals.get(host, 1.0)
        last = self._last.get(host)
        if last is not None:
            wait = interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last[host] = time.monotonic()

    @contextlib.contextmanager
    def _shared_slot(self, host: str):
        """Cross-process: one request in flight at a time for a host family, and a minimum interval between the end
        of one request and the start of the next (FastNear answers 429 to concurrent requests from one machine)."""
        suffix = next((x for x in self._shared if host.endswith(x)), None)
        if suffix is None:
            yield
            return
        interval = self._shared[suffix]
        path = self.cache_dir / f".throttle_{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.seek(0)
                txt = fh.read().strip()
                wait = interval - (time.time() - (float(txt) if txt else 0.0))
                if wait > 0:
                    time.sleep(wait)
                yield
            finally:
                fh.seek(0)
                fh.truncate()
                fh.write(f"{time.time():.6f}")
                fh.flush()
                fcntl.flock(fh, fcntl.LOCK_UN)

    @staticmethod
    def _key(method: str, url: str, body: Any) -> str:
        raw = json.dumps([method, url, body], sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    def _cache_path(self, host: str, key: str) -> Path:
        return self.cache_dir / host / key[:2] / f"{key}.json"

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg, file=sys.stderr, flush=True)

    # ------------------------------------------------------------------ core
    def request(self, method: str, url: str, *, params: dict | None = None, body: Any = None,
                immutable: bool = False, max_age_s: float | None = None) -> Any:
        full_url = url + ("?" + urlencode(params) if params else "")
        host = urlsplit(full_url).netloc
        key = self._key(method, full_url, body)
        cpath = self._cache_path(host, key)
        st = self.stats[host]
        if immutable and cpath.exists():
            st.cache_hits += 1
            return json.loads(cpath.read_text())["response"]
        if max_age_s is not None and cpath.exists():
            cached = json.loads(cpath.read_text())
            if time.time() - cached.get("fetched_at_unix", 0) <= max_age_s:
                st.cache_hits += 1
                return cached["response"]

        def _once() -> Any:
            self._throttle(host)
            st.requests += 1
            try:
                with self._shared_slot(host):
                    if method == "GET":
                        r = self._client.get(full_url)
                    else:
                        r = self._client.post(full_url, json=body)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                st.errors += 1
                raise TransientError(f"{type(exc).__name__} on {full_url}") from exc
            if r.status_code == 429:
                st.rate_limited += 1
                retry_after = r.headers.get("retry-after")
                pause = float(retry_after) if retry_after and retry_after.isdigit() else 30.0
                # adaptive politeness: every 429 makes this host 25% slower for the rest of the run (cap 10 s)
                self._intervals[host] = min(10.0, self._intervals.get(host, 1.0) * 1.25)
                self._log(f"  429 from {host}; sleeping {pause:.0f}s; min interval now {self._intervals[host]:.2f}s")
                time.sleep(min(pause, 300.0))
                raise TransientError(f"429 on {full_url}")
            if r.status_code >= 500:
                st.errors += 1
                raise TransientError(f"HTTP {r.status_code} on {full_url}: {r.text[:200]}")
            if r.status_code >= 400:
                st.errors += 1
                # some RPC nodes return JSON-RPC errors (e.g. UNKNOWN_BLOCK for a skipped height) with HTTP 4xx
                try:
                    body_json = r.json()
                except ValueError:
                    body_json = None
                if isinstance(body_json, dict) and isinstance(body_json.get("error"), dict):
                    err = RpcError(body_json["error"])
                    if err.cause in TRANSIENT_RPC_CAUSES:
                        raise TransientError(str(err))
                    raise err
                raise httpx.HTTPStatusError(f"HTTP {r.status_code} on {full_url}: {r.text[:300]}",
                                            request=r.request, response=r)
            st.bytes += len(r.content)
            data = r.json()
            if isinstance(data, dict) and "jsonrpc" in data and "error" in data:
                err = RpcError(data["error"])
                if err.cause in TRANSIENT_RPC_CAUSES:
                    raise TransientError(str(err))
                raise err
            return data

        retrying = Retrying(
            stop=stop_after_attempt(self._cfg["max_attempts"]),
            wait=wait_exponential_jitter(initial=self._cfg["backoff_initial_s"], max=self._cfg["backoff_max_s"]),
            retry=retry_if_exception_type(TransientError),
            reraise=True,
            before_sleep=lambda rs: (setattr(st, "retries", st.retries + 1),
                                     self._log(f"  retry {rs.attempt_number} {host}: {rs.outcome.exception()}")),
        )
        data = retrying(_once)
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text(json.dumps({"method": method, "url": full_url, "body": body,
                                     "fetched_at_unix": int(time.time()), "response": data}))
        return data

    def get_json(self, url: str, params: dict | None = None, *, immutable: bool = False,
                 max_age_s: float | None = None) -> Any:
        return self.request("GET", url, params=params, immutable=immutable, max_age_s=max_age_s)

    def post_json(self, url: str, body: Any, *, immutable: bool = False, max_age_s: float | None = None) -> Any:
        return self.request("POST", url, body=body, immutable=immutable, max_age_s=max_age_s)

    def rpc(self, url: str, method: str, params: Any, *, immutable: bool = False,
            max_age_s: float | None = None) -> Any:
        body = {"jsonrpc": "2.0", "id": "nearthesis", "method": method, "params": params}
        return self.request("POST", url, body=body, immutable=immutable, max_age_s=max_age_s)["result"]

    def stats_for(self, *hosts: str) -> dict[str, int]:
        agg = HostStats()
        for h in hosts:
            s = self.stats.get(h)
            if s:
                for k in vars(agg):
                    setattr(agg, k, getattr(agg, k) + getattr(s, k))
        return vars(agg).copy()

    def close(self) -> None:
        self._client.close()
