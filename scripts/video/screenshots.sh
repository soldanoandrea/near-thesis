#!/usr/bin/env bash
# Screenshots of the dashboard, one 1280x720 PNG per card, with headless Chrome (no Playwright, no server).
# dashboard.html#capture=<id> shows a single card filling the window (src/nearthesis/web/static/app.js); an optional
# &note=<text> adds a heading for video frames.
#
# Usage: scripts/video/screenshots.sh [out_dir] [shot_list]
#   out_dir    default docs/media/screens
#   shot_list  optional file, one shot per line: <name> <hash>, e.g. "03_intents capture=intents&note=2%2F6..."
#              (default: one shot per card in $CARDS, named after the card, without a note)
# Needs Google Chrome or Chromium and ffmpeg. The page loads the pinned Plotly.js from cdnjs: this needs the network.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:-$REPO/docs/media/screens}"
LIST="${2:-}"
CARDS="${CARDS:-hero classes signers intents revenue treasury supply multiples developers scorecard predictions outro}"
W=1280 H=720

CHROME="${CHROME:-}"
if [ -z "$CHROME" ]; then
  for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" "/Applications/Chromium.app/Contents/MacOS/Chromium" \
           "$(command -v google-chrome || true)" "$(command -v chromium || true)" "$(command -v chromium-browser || true)"; do
    if [ -n "$c" ] && [ -x "$c" ]; then CHROME="$c"; break; fi
  done
fi
[ -n "$CHROME" ] || { echo "[screens] Chrome/Chromium not found (set CHROME=/path/to/chrome)"; exit 1; }
command -v ffmpeg >/dev/null || { echo "[screens] ffmpeg not found"; exit 1; }
[ -f "$REPO/site/dashboard.html" ] || { echo "[screens] site/dashboard.html missing: run make site"; exit 1; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/near-thesis-screens.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
URL="file://$REPO/site/dashboard.html"
chrome() { "$CHROME" --headless=new --disable-gpu --no-first-run --no-default-browser-check --user-data-dir="$TMP/profile" \
             --hide-scrollbars --force-device-scale-factor=1 --virtual-time-budget=20000 "$@" 2>/dev/null; }

if [ -z "$LIST" ]; then
  LIST="$TMP/shots.txt"
  for c in $CARDS; do echo "$c capture=$c"; done > "$LIST"
fi

# Headless Chrome's viewport is shorter than --window-size by a platform-dependent amount: measure it once.
ih="$(chrome --window-size=$W,$H --dump-dom "$URL#capture=hero" | grep -o 'data-ih="[0-9]*"' | grep -o '[0-9][0-9]*' || true)"
[ -n "$ih" ] || { echo "[screens] could not read the viewport height"; exit 1; }
WH=$((H + H - ih))
mkdir -p "$OUT"
while read -r name hash; do
  [ -n "$name" ] || continue
  if ! chrome --window-size=$W,$WH --dump-dom "$URL#$hash" | grep -q 'data-rendered="plotly"'; then
    echo "[screens] Plotly.js did not load (offline?): the charts would be missing"; exit 1
  fi
  chrome --window-size=$W,$WH --screenshot="$TMP/$name.png" "$URL#$hash" >/dev/null
  ffmpeg -v error -y -i "$TMP/$name.png" -vf "crop=$W:$H:0:0" "$OUT/$name.png"
  echo "[screens] $OUT/$name.png"
done < "$LIST"
