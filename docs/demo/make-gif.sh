#!/usr/bin/env bash
# One command to produce the README hero GIF from the REAL running app.
#
#   1. ensure the deterministic sample PDF exists
#   2. install playwright (local to docs/demo) + chromium if needed
#   3. drive the live UI and record a video (capture.mjs)
#   4. transcode the video to an optimized, looping docs/demo/demo.gif
#   5. wire the README hero to point at it
#
# Prereqs you must have running FIRST (see docs/demo/README.md):
#   - web app on $WEB_URL   (default http://localhost:3000)
#   - FastAPI on  $API_URL  (default http://localhost:8000)
# Prereqs on PATH: node, python3, and ffmpeg (gifski used automatically if present).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

WEB_URL="${WEB_URL:-http://localhost:3000}"
API_URL="${API_URL:-http://localhost:8000}"
FPS="${FPS:-12}"
WIDTH="${WIDTH:-1000}"
OUT_GIF="${OUT_GIF:-$HERE/demo.gif}"
RAW="$HERE/raw.webm"

say() { printf '\033[1;33m▶ %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

command -v node >/dev/null    || die "node not found"
command -v python3 >/dev/null || die "python3 not found"
command -v ffmpeg >/dev/null  || die "ffmpeg not found — install it (brew install ffmpeg / apt-get install ffmpeg). gifski is optional but improves quality."

# Fail fast if the app isn't up, with a helpful message.
curl -fsS -o /dev/null "$WEB_URL" 2>/dev/null || die "web app not reachable at $WEB_URL — start it first (see docs/demo/README.md)"
curl -fsS -o /dev/null "$API_URL/api/health" 2>/dev/null \
  || curl -fsS -o /dev/null "$API_URL/api/healthz" 2>/dev/null \
  || say "warning: API health check failed at $API_URL — continuing anyway"

say "1/5  sample PDF"
[ -f "$HERE/sample-paper.pdf" ] || python3 "$HERE/make-sample-pdf.py"

say "2/5  playwright + chromium"
if [ ! -d "$HERE/node_modules/playwright" ]; then
  ( cd "$HERE" && npm install --no-audit --no-fund )
fi
# Chromium may already be provisioned (PLAYWRIGHT_BROWSERS_PATH). Install if missing.
( cd "$HERE" && npx playwright install chromium >/dev/null 2>&1 || true )

say "3/5  record the live UI"
rm -f "$HERE"/*.webm
( cd "$HERE" && WEB_URL="$WEB_URL" API_URL="$API_URL" OUT_DIR="$HERE" node capture.mjs )
NEWEST_WEBM="$(ls -t "$HERE"/*.webm 2>/dev/null | head -n1 || true)"
[ -n "$NEWEST_WEBM" ] || die "no video produced by capture.mjs"
mv -f "$NEWEST_WEBM" "$RAW"

say "4/5  transcode -> $OUT_GIF"
if command -v gifski >/dev/null; then
  # gifski gives the best quality/size. Feed it frames via ffmpeg.
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  ffmpeg -y -loglevel error -i "$RAW" -vf "fps=$FPS,scale=$WIDTH:-1:flags=lanczos" "$TMP/f%04d.png"
  gifski --fps "$FPS" --width "$WIDTH" --quality 90 -o "$OUT_GIF" "$TMP"/f*.png
else
  # ffmpeg two-pass palette: good quality, small file, universally available.
  PAL="$(mktemp --suffix=.png 2>/dev/null || echo "$HERE/_pal.png")"
  ffmpeg -y -loglevel error -i "$RAW" \
    -vf "fps=$FPS,scale=$WIDTH:-1:flags=lanczos,palettegen=stats_mode=diff" "$PAL"
  ffmpeg -y -loglevel error -i "$RAW" -i "$PAL" \
    -lavfi "fps=$FPS,scale=$WIDTH:-1:flags=lanczos,paletteuse=dither=bayer:bayer_scale=3" \
    -loop 0 "$OUT_GIF"
  rm -f "$PAL"
fi

SIZE_KB=$(( $(wc -c < "$OUT_GIF") / 1024 ))
say "5/5  wire README hero"
python3 "$HERE/_wire-readme.py"

printf '\033[1;32m✓ done — %s (%s KB)\033[0m\n' "$OUT_GIF" "$SIZE_KB"
[ "$SIZE_KB" -gt 5120 ] && cat <<EOF
  Note: GIF is >5 MB. Shrink with:
    FPS=10 WIDTH=880 bash docs/demo/make-gif.sh
  or install gifski for better compression.
EOF
exit 0
