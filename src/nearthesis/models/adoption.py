"""(c) Adoption model on organic activity: log-linear trend vs logistic S-curve, with a rolling-origin out-of-sample
backtest and residual-bootstrap forecast ranges. Pure numpy.

Models for a positive monthly series y_t (t = 0, 1, ... months):
  loglinear : log y_t = a + b t + e_t                        (constant growth or decay; b > 0 = growth)
  logistic  : y_t = K / (1 + exp(-r (t - t0))) x exp(e_t)    (S-curve; r < 0 gives a decaying S-curve)
              fitted by profiling K over a log grid (above max y) with OLS of log(y / (K - y)) on t, selecting the K
              that minimizes the squared error of log y
  naive     : log y_{T+h} = log y_T                           (random walk benchmark)
Errors are measured in log space (|log forecast - log actual|), so they read as relative errors.
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl

MODELS = ("loglinear", "logistic", "naive")


def fit(model: str, t: np.ndarray, y: np.ndarray) -> dict:
    t, y = np.asarray(t, float), np.asarray(y, float)
    ly = np.log(y)
    if model == "naive":
        return {"model": model, "last_t": t[-1], "last_ly": ly[-1], "sigma": float(np.std(np.diff(ly), ddof=1))
                if len(ly) > 2 else 0.0}
    if model == "loglinear":
        b, a = np.polyfit(t, ly, 1)
        res = ly - (a + b * t)
        return {"model": model, "a": float(a), "b": float(b), "sigma": float(np.std(res, ddof=2)) if len(t) > 2 else 0.0}
    if model == "logistic":
        best = None
        ymax = float(y.max())
        for k in ymax * np.exp(np.linspace(math.log(1.0005), math.log(50.0), 240)):
            z = np.log(y / (k - y))
            r, c = np.polyfit(t, z, 1)
            pred = math.log(k) - np.log1p(np.exp(-(r * t + c)))
            sse = float(np.sum((ly - pred) ** 2))
            if best is None or sse < best[0]:
                best = (sse, float(k), float(r), float(c))
        sse, k, r, c = best
        return {"model": model, "K": k, "r": r, "t0": -c / r if r else float("nan"), "c": c,
                "sigma": math.sqrt(sse / max(len(t) - 3, 1)), "K_at_grid_edge": k >= ymax * 49.0}
    raise ValueError(model)


def predict(p: dict, t: np.ndarray) -> np.ndarray:
    """Point forecast of log y at times t."""
    t = np.asarray(t, float)
    if p["model"] == "naive":
        return np.full_like(t, p["last_ly"])
    if p["model"] == "loglinear":
        return p["a"] + p["b"] * t
    return math.log(p["K"]) - np.log1p(np.exp(-(p["r"] * t + p["c"])))


def backtest(t: np.ndarray, y: np.ndarray, horizons=(3, 6), min_train: int = 12) -> pl.DataFrame:
    """Rolling origin: fit on [0, T), forecast T-1+h, for every T >= min_train with data at T-1+h."""
    t, y = np.asarray(t, float), np.asarray(y, float)
    rows = []
    for T in range(min_train, len(t)):
        for m in MODELS:
            p = fit(m, t[:T], y[:T])
            for h in horizons:
                j = T - 1 + h
                if j >= len(t):
                    continue
                err = float(predict(p, t[j:j + 1])[0] - math.log(y[j]))
                rows.append({"model": m, "origin_t": int(t[T - 1]), "horizon": h, "log_error": err})
    return pl.DataFrame(rows, schema={"model": pl.Utf8, "origin_t": pl.Int64, "horizon": pl.Int64,
                                      "log_error": pl.Float64})


def backtest_summary(bt: pl.DataFrame) -> pl.DataFrame:
    return (bt.group_by(["model", "horizon"]).agg(pl.len().alias("forecasts"),
                                                 pl.col("log_error").abs().mean().alias("mean_abs_log_error"),
                                                 pl.col("log_error").mean().alias("mean_log_error"))
            .sort(["horizon", "mean_abs_log_error", "model"]))


def forecast_ranges(t: np.ndarray, y: np.ndarray, model: str, horizons=(12, 24, 36), n_boot: int = 500,
                    seed: int = 0, q=(0.05, 0.5, 0.95)) -> pl.DataFrame:
    """Residual bootstrap: refit on y* = fitted x exp(resampled residuals), forecast, add a resampled residual."""
    t, y = np.asarray(t, float), np.asarray(y, float)
    p = fit(model, t, y)
    fitted = predict(p, t) if model != "naive" else np.r_[np.log(y[0]), np.log(y[:-1])]
    res = np.log(y) - fitted
    rng = np.random.default_rng(seed)
    tf = t[-1] + np.asarray(horizons, float)
    sims = np.empty((n_boot, len(horizons)))
    for b in range(n_boot):
        if model == "naive":
            d = np.diff(np.log(y))
            steps = rng.choice(d - d.mean(), size=(int(max(horizons)),), replace=True)  # random walk, no drift
            path = np.log(y[-1]) + np.cumsum(steps)
            sims[b] = path[np.asarray(horizons) - 1]
            continue
        ystar = np.exp(fitted + rng.choice(res, size=len(res), replace=True))
        pb = fit(model, t, ystar)
        sims[b] = predict(pb, tf) + rng.choice(res, size=len(horizons), replace=True)
    rows = []
    for i, h in enumerate(horizons):
        qs = np.quantile(np.exp(sims[:, i]), q)
        rows.append({"model": model, "horizon_months": int(h), "p05": float(qs[0]), "p50": float(qs[1]),
                     "p95": float(qs[2]), "last_value": float(y[-1])})
    return pl.DataFrame(rows)
