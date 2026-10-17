#!/bin/bash
# Double click this file. It starts everything the outreach autopilot needs and opens your CRM.
# If the autopilot toggle was left on, it resumes about 10 seconds after the CRM opens.
CRM="$(cd "$(dirname "$0")/.." && pwd)"
GEN="$HOME/instagram-video-generator"
LOGS="$HOME/Library/Logs/clipper"
mkdir -p "$LOGS"
# Use the project's own Python (has Playwright, ffmpeg, the voice engines) when it exists, else the system one.
PY="$CRM/tools/.venv/bin/python"
[ -x "$PY" ] || PY=python3

if [ ! -d "$GEN" ]; then
  echo "No clipper app on this computer (only needed for the Drive hosting mode); skipping."
elif ! lsof -ti :5001 >/dev/null 2>&1; then
  (cd "$GEN" && nohup python3 app.py >> "$LOGS/app.log" 2>&1 &)
  echo "Started the clipper app (port 5001)."
else
  echo "Clipper app already running."
fi
if ! lsof -ti :8765 >/dev/null 2>&1; then
  (cd "$CRM" && nohup "$PY" tools/local_runner.py >> "$LOGS/helper.log" 2>&1 &)
  echo "Started the helper (port 8765)."
else
  echo "Helper already running."
fi
for i in 1 2 3 4 5 6 7 8 9 10; do curl -s -m 2 localhost:8765/status >/dev/null 2>&1 && break; sleep 1; done
curl -s -m 2 localhost:8765/status >/dev/null 2>&1 && echo "Helper is answering." || echo "WARNING: the helper did not answer. See $LOGS/helper.log"
echo "The Mac is NOT kept awake by this launcher. The CRM shows a coffee cup indicator and keeps it awake only while the autopilot works."
open "https://pharaohm33.github.io/cold-email-outreach-crm/"
echo
echo "Done. In the CRM: Email tab > Autopilot > turn Repeating on. Logs: $LOGS"
echo "You can close this window; everything keeps running."
