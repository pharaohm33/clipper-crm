#!/bin/bash
# Double click this file. It starts everything the outreach autopilot needs and opens your CRM.
# If the autopilot toggle was left on, it resumes about 10 seconds after the CRM opens.
CRM="$(cd "$(dirname "$0")/.." && pwd)"
GEN="$HOME/instagram-video-generator"
LOGS="$HOME/Library/Logs/clipper"
mkdir -p "$LOGS"

if ! lsof -ti :5001 >/dev/null 2>&1; then
  (cd "$GEN" && nohup python3 app.py >> "$LOGS/app.log" 2>&1 &)
  echo "Started the clipper app (port 5001)."
else
  echo "Clipper app already running."
fi
if ! lsof -ti :8765 >/dev/null 2>&1; then
  (cd "$CRM" && nohup python3 tools/local_runner.py >> "$LOGS/helper.log" 2>&1 &)
  echo "Started the helper (port 8765)."
else
  echo "Helper already running."
fi
sleep 5
echo "The Mac is NOT kept awake by this launcher. The CRM shows a coffee cup indicator and keeps it awake only while the autopilot works."
open "https://pharaohm33.github.io/clipper-crm/"
echo
echo "Done. In the CRM: Email tab > Autopilot > turn Repeating on. Logs: $LOGS"
echo "You can close this window; everything keeps running."
