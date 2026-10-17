#!/usr/bin/env python3
"""
Kokoro voice, run with the Kokoro venv:  echo '{"text": "...", "voice": "am_michael", "out": "/tmp/x.wav"}' | tools/.kokoro_venv/bin/python tools/kokoro_say.py

Writes the speech to `out` (24 kHz mono wav, the silence Kokoro leaves around each sentence trimmed, 0.12 s between sentences) and prints one JSON line:
{"seconds": 12.3, "words": [[start, end, "word"], ...]} with Kokoro's own word times, which ad_video.py lines up with the caption text.
"""
import json
import re
import sys

import numpy as np
import soundfile as sf
from kokoro import KPipeline

SR = 24000
GAP = int(0.12 * SR)


def trim(a, pad=0.02):
    hop = int(SR * 0.01)
    n = len(a) // hop
    e = np.array([np.sqrt((a[i * hop:(i + 1) * hop] ** 2).mean()) for i in range(n)]) if n else np.array([])
    loud = np.where(e > max(e.max() * 0.02, 1e-4))[0] if n else []
    if len(loud) == 0:
        return 0, len(a)
    return max(0, int((loud[0] * 0.01 - pad) * SR)), min(len(a), int(((loud[-1] + 1) * 0.01 + pad) * SR))


def main():
    req = json.load(sys.stdin)
    pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    parts, words, t = [], [], 0.0
    for r in pipe(req["text"], voice=req.get("voice", "am_michael"), speed=float(req.get("speed", 1.0)), split_pattern=r"(?<=[.!?])\s+"):
        a = np.asarray(r.audio.numpy() if hasattr(r.audio, "numpy") else r.audio, dtype=np.float32)
        s, e = trim(a)
        for tok in (r.tokens or []):
            if tok.start_ts is not None and tok.end_ts is not None and re.search(r"[A-Za-z0-9]", tok.text):
                words.append([round(t + max(tok.start_ts - s / SR, 0), 3), round(t + max(tok.end_ts - s / SR, 0), 3), tok.text])
        parts += [a[s:e], np.zeros(GAP, dtype=np.float32)]
        t += (e - s) / SR + GAP / SR
    audio = np.concatenate(parts[:-1])
    sf.write(req["out"], audio, SR)
    print(json.dumps({"seconds": round(len(audio) / SR, 3), "words": words}))


if __name__ == "__main__":
    main()
