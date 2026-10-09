#!/bin/bash
# Double click this file to stop everything the outreach system started.
# It stops: the helper, the clipper app, the Google AI Chrome window, any "keep awake", and any lead search or fit check in progress.
# It does NOT touch your normal Chrome, your emails, your drafts or your CRM data.

stop_port() {  # $1 = port, $2 = label
  local pids; pids="$(lsof -ti :"$1" 2>/dev/null)"
  if [ -n "$pids" ]; then kill $pids 2>/dev/null; echo "Stopped $2."; else echo "$2 was not running."; fi
}

stop_port 8765 "the helper"            # first, so it cannot restart the clipper app
pkill -f "fit_check.py" 2>/dev/null
pkill -f "google_ai_to_crm.py" 2>/dev/null
sleep 1
stop_port 5001 "the clipper app"
if pgrep -f "remote-debugging-port=9223" >/dev/null; then pkill -TERM -f "remote-debugging-port=9223"; echo "Closed the Google AI Chrome window."; else echo "The Google AI Chrome window was not open."; fi
if pgrep -f "caffeinate -dimsu" >/dev/null; then pkill -f "caffeinate -dimsu"; echo "Stopped keeping the Mac awake. It can sleep again."; else echo "Nothing was keeping the Mac awake."; fi
sleep 2

echo; echo "Check:"
for p in 8765 5001 9223; do
  if lsof -ti :"$p" >/dev/null 2>&1; then echo "  port $p: STILL RUNNING"; else echo "  port $p: stopped"; fi
done
echo
echo "Everything is stopped. To start again: double click start_outreach.command, then in the CRM press Keep going or Run once now."
