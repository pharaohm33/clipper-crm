#!/bin/bash
# One command to set up everything the video maker needs on a Mac (safe to run again; it skips what is already there).
#   bash tools/setup_video_tools.sh          the default voice (Kokoro, Michael), the recorder, ffmpeg
#   bash tools/setup_video_tools.sh --dia    also the slower cloned-voice engine (about 6 GB, needs 16 GB of RAM or more)
# Needs: python3 and an internet connection. Google Chrome must be installed (the recorder drives it).
set -e
T="$(cd "$(dirname "$0")" && pwd)"
UV="$HOME/.uvboot/bin/uv"
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$UV" ]; then
  echo "Installing uv (a small Python installer, from PyPI)..."
  python3 -m venv "$HOME/.uvboot" && "$HOME/.uvboot/bin/pip" install -q uv
fi
command -v uv >/dev/null 2>&1 && UV="$(command -v uv)"
[ -d "/Applications/Google Chrome.app" ] || echo "WARNING: Google Chrome is not installed in /Applications. The recorder needs it."

if [ ! -x "$T/.venv/bin/python" ]; then
  echo "Creating the main environment..."
  "$UV" venv --python 3.11 "$T/.venv"
fi
echo "Installing the recorder, ffmpeg and the quality check..."
"$UV" pip install -q --python "$T/.venv/bin/python" playwright requests edge-tts pillow static-ffmpeg faster-whisper "opencv-python-headless<5"
"$T/.venv/bin/python" -c "import static_ffmpeg; static_ffmpeg.add_paths()" >/dev/null
"$T/.venv/bin/playwright" install chromium >/dev/null

if [ ! -x "$T/.kokoro_venv/bin/python" ]; then
  echo "Creating the Kokoro voice environment..."
  "$UV" venv --python 3.11 "$T/.kokoro_venv"
fi
"$UV" pip install -q --python "$T/.kokoro_venv/bin/python" kokoro soundfile pip
echo "Downloading the Kokoro voice model (first time only)..."
echo '{"text": "Setup check.", "voice": "am_michael", "out": "/tmp/kokoro_setup_check.wav"}' | "$T/.kokoro_venv/bin/python" -I "$T/kokoro_say.py" >/dev/null 2>&1 \
  && echo "Kokoro works." || echo "WARNING: Kokoro did not run. Run this script again, or see tools/.kokoro_venv."

if [ "$1" = "--dia" ]; then
  if [ ! -x "$T/.dia_venv/bin/python" ]; then "$UV" venv --python 3.11 "$T/.dia_venv"; fi
  echo "Installing Dia (large)..."
  "$UV" pip install -q --python "$T/.dia_venv/bin/python" "git+https://github.com/nari-labs/dia.git" soundfile faster-whisper
  "$UV" pip install -q --python "$T/.dia_venv/bin/python" --no-deps resemblyzer webrtcvad-wheels
  "$UV" pip install -q --python "$T/.dia_venv/bin/python" librosa scipy
  echo "Dia installed. Use the voice 'Emmanuel cloned voice' in the CRM; its server starts by itself."
fi
echo
echo "Done. Start everything with tools/start_outreach.command (or: tools/.venv/bin/python tools/local_runner.py)."
echo "Still by hand, once: open the CRM, press Connect Loom and log in."
