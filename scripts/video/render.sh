#!/usr/bin/env bash
# `make video`: render the demo video (docs/DEMO_SCRIPT.md) to docs/media/demo.mp4 (H.264, <= 3 minutes, <= 25 MB)
# and refresh the dashboard screenshots in docs/media/screens/.
#
# 1. Screenshots of the dashboard cards with headless Chrome (scripts/video/screenshots.sh), with a heading per scene.
# 2. The terminal scene: docs/demo.tape recorded by VHS in a throw-away clone of HEAD, played at 2x.
# 3. ffmpeg joins title, terminal, chart scenes and the closing frame, each with a short fade.
# Nothing leaves the machine (never `vhs publish`); the screenshots load the pinned Plotly.js from cdnjs.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MAX_SECONDS="${VIDEO_MAX_SECONDS:-180}"
MAX_MP4_BYTES=$((25 * 1024 * 1024))
FPS=30

for tool in vhs ttyd ffmpeg ffprobe git make uv; do
  command -v "$tool" >/dev/null 2>&1 || { echo "make video needs '$tool' (macOS: brew install vhs, which brings ttyd and ffmpeg)"; exit 1; }
done

WORK="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/near-thesis-video.XXXXXX")" && pwd -P)"
trap 'rm -rf "$WORK"' EXIT

echo "[video] site and screenshots"
make -C "$REPO" site >/dev/null
"$REPO/scripts/video/screenshots.sh" "$REPO/docs/media/screens" >/dev/null

# name, seconds, capture hash (the note is a heading for the frame; numbers stay in the cards themselves)
cat > "$WORK/scenes.txt" <<'SCENES'
00_title 7 capture=hero&note=NEAR%20HACKATHON%202026%20%C2%B7%20track%20thesis%20%C2%B7%20judged%20on%20the%20evidence
02_classes 14 capture=classes&note=1%2F6%20%C2%B7%20Organic%20collapse%3A%20who%20actually%20sends%20NEAR's%20transactions
03_signers 13 capture=signers&note=1%2F6%20%C2%B7%20Organic%20collapse%3A%20daily%20active%20signers%2C%20and%20why%20NearBlocks%20undercounts%20them
04_intents 15 capture=intents&note=2%2F6%20%C2%B7%20NEAR%20Intents%3A%20real%2C%20but%20the%20reported%20volume%20looks%20two-sided
05_revenue 12 capture=revenue&note=3%2F6%20%C2%B7%20Revenue%20verified%3A%20DefiLlama's%20captured%20revenue%2C%20rebuilt%20from%20on-chain%20flows
06_treasury 15 capture=treasury&note=4%2F6%20%C2%B7%20The%20treasury%20trail%3A%20where%20the%20April-May%202026%20outflows%20went
07_supply 12 capture=supply&note=5%2F6%20%C2%B7%20Dilution%3A%202.5%25%20issuance%20vs%20HSP-029%2C%20after%20burn%20and%20buybacks
08_multiples 10 capture=multiples&note=5%2F6%20%C2%B7%20Valuation%20depends%20on%20whether%20Intents%20counts
09_predictions 15 capture=predictions&note=6%2F6%20%C2%B7%20What%20would%20change%20our%20mind%3A%20dated%20predictions%2C%20hashed%20and%20tagged
10_outro 8 capture=outro
SCENES
awk '{print $1, $3}' "$WORK/scenes.txt" > "$WORK/shots.txt"
"$REPO/scripts/video/screenshots.sh" "$WORK/frames" "$WORK/shots.txt" >/dev/null

echo "[video] terminal scene: fresh clone in $WORK/near-thesis, recording make reproduce (about 1-2 minutes)"
git clone -q "$REPO" "$WORK/near-thesis"
cp "$REPO/docs/demo.tape" "$WORK/near-thesis/.demo.tape"   # the working-copy tape; hidden from `ls` in the video
( cd "$WORK/near-thesis" && vhs -q .demo.tape && rm -f .demo.tape )
[ -s "$WORK/near-thesis/terminal.mp4" ] || { echo "[video] VHS produced no terminal.mp4"; exit 1; }

echo "[video] composing"
enc=(-c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r $FPS -an)
clip() {  # clip <png> <seconds> <out>
  local d="$2"; local fo; fo="$(awk -v d="$d" 'BEGIN { printf "%.2f", d - 0.4 }')"
  ffmpeg -v error -y -loop 1 -framerate $FPS -t "$d" -i "$1" \
    -vf "scale=1280:720,format=yuv420p,fade=t=in:st=0:d=0.4,fade=t=out:st=$fo:d=0.4" "${enc[@]}" "$3"
}
: > "$WORK/list.txt"
while read -r name secs _hash; do
  clip "$WORK/frames/$name.png" "$secs" "$WORK/$name.mp4"
  if [ "$name" = "00_title" ]; then
    ffmpeg -v error -y -i "$WORK/near-thesis/terminal.mp4" \
      -vf "setpts=0.5*PTS,fps=$FPS,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p" \
      "${enc[@]}" "$WORK/01_terminal.mp4"
    printf "file '%s'\nfile '%s'\n" "$WORK/$name.mp4" "$WORK/01_terminal.mp4" >> "$WORK/list.txt"
  else
    printf "file '%s'\n" "$WORK/$name.mp4" >> "$WORK/list.txt"
  fi
done < "$WORK/scenes.txt"

out="$WORK/demo.mp4"
ffmpeg -v error -y -f concat -safe 0 -i "$WORK/list.txt" -c:v libx264 -preset slow -crf 24 -pix_fmt yuv420p \
  -movflags +faststart -an "$out"
if [ "$(wc -c < "$out")" -gt "$MAX_MP4_BYTES" ]; then
  ffmpeg -v error -y -f concat -safe 0 -i "$WORK/list.txt" -c:v libx264 -preset slow -crf 30 -pix_fmt yuv420p \
    -movflags +faststart -an "$out"
fi
duration="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out")"
if ! awk -v d="$duration" -v m="$MAX_SECONDS" 'BEGIN { exit (d <= m) ? 0 : 1 }'; then
  echo "[video] ${duration}s is longer than ${MAX_SECONDS}s: shorten the scenes in scripts/video/render.sh"; exit 1
fi
mkdir -p "$REPO/docs/media"
cp "$out" "$REPO/docs/media/demo.mp4"
echo "[video] docs/media/demo.mp4: ${duration}s, $(wc -c < "$REPO/docs/media/demo.mp4" | tr -d ' ') bytes"
