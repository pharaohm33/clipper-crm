#!/bin/bash
# Download just a slice of a YouTube video (fast, no full download) to make a sample clip from.
#   tools/grab_sample.sh "<youtube url>" [start] [end] [outfolder]
#   tools/grab_sample.sh "https://www.youtube.com/watch?v=XXXX" 12:00 17:00
# Defaults: start 10:00, end 15:00 (5 minutes), saved to ~/Downloads/clip-samples
# Needs ffmpeg (brew install ffmpeg) and yt-dlp (python3 -m yt_dlp or the yt-dlp command).
set -e
URL="$1"; START="${2:-10:00}"; END="${3:-15:00}"; OUT="${4:-$HOME/Downloads/clip-samples}"
[ -z "$URL" ] && { echo "Usage: $0 \"<youtube url>\" [start] [end] [outfolder]"; exit 1; }
mkdir -p "$OUT"
if command -v yt-dlp >/dev/null 2>&1; then YT=(yt-dlp); else YT=(python3 -m yt_dlp); fi
# try a few YouTube client modes; older yt-dlp builds often fail on the default one
for CLIENT in "tv_simply,android_vr" "default" "ios"; do
  ARGS=(--no-playlist --download-sections "*${START}-${END}" --force-keyframes-at-cuts
        -f "bv*[height<=1080]+ba/b[height<=1080]" --merge-output-format mp4
        -o "$OUT/%(title).60s [${START//:/-}].%(ext)s" --print after_move:filepath)
  [ "$CLIENT" != "default" ] && ARGS+=(--extractor-args "youtube:player_client=$CLIENT")
  if FILE=$("${YT[@]}" "${ARGS[@]}" "$URL" 2>/dev/null | tail -1) && [ -n "$FILE" ] && [ -f "$FILE" ]; then
    echo "Saved: $FILE"; open -R "$FILE" 2>/dev/null || true; exit 0
  fi
  echo "client '$CLIENT' failed, trying next..." >&2
done
echo "All attempts failed. Update yt-dlp:  brew install yt-dlp   (then run again)" >&2; exit 1
