#!/usr/bin/env python3
"""
Local Dia voice server. Run with the Dia venv:  tools/.dia_venv/bin/python tools/dia_server.py

POST /speak  {"text": "The whole script."}  ->  audio/wav (44.1 kHz mono), spoken in one generation in the saved reference voice, silence trimmed off both ends.
             Header X-Words: JSON [[start, end, word], ...] from transcribing the result (real word times for captions).
GET  /health ->  "ok" once everything is loaded.

One generation keeps one voice from the first word to the last. Dia holds about 35 s of audio per generation (decoder limit 3072 steps, the reference clip included),
so callers send a whole script when it fits (about 125 words or fewer) and two or more big pieces only when it does not.

The voice is cloned from a short reference (tools/assets/dia_ref_short.wav + .txt, 4.5 s, [S1] only). Every take is transcribed and compared with the text, and its voice is compared
with the full reference (tools/assets/dia_ref.wav); a take that misreads words or drifts to another voice is redone with the next seed.
Only the narrator is ever generated: no second-speaker tag, and nothing but the new text is returned.
"""
import difflib
import io
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio
from dia.model import Dia
from faster_whisper import WhisperModel
from resemblyzer import VoiceEncoder, preprocess_wav

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
PORT = int(os.getenv("DIA_PORT", "8766"))
SEEDS = (7, 11, 21, 42, 5, 13)  # tried in order until the take passes
MIN_MATCH, MIN_VOICE = 0.92, 0.88  # a take must reach both; the best take is used if none does, but not below the floors
FLOOR_MATCH, FLOOR_VOICE = 0.85, 0.80
SR = 44100
MODEL = "nari-labs/Dia-1.6B-0626"

lock = threading.Lock()
state = {}


def load():
    dev = torch.device("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")
    m = Dia.from_pretrained(MODEL, compute_dtype="float16", device=dev)
    state["asr"] = WhisperModel("base.en", device="cpu", compute_type="int8")
    enc = VoiceEncoder("cpu")
    ref, sr = sf.read(str(ASSETS / "dia_ref.wav"), dtype="float32")
    state["enc"] = enc
    state["ref_emb"] = enc.embed_utterance(preprocess_wav(ref, source_sr=sr))
    state["ref_txt"] = (ASSETS / "dia_ref_short.txt").read_text(encoding="utf-8").strip()
    state["prompt"] = m.load_audio(str(ASSETS / "dia_ref_short.wav"))  # encoded once, reused for every take
    state["model"] = m  # last: /health answers 200 only once everything is ready
    print("dia ready on", dev, flush=True)


def trim(a, pad=0.04):
    """Cuts the silence at the start and end (Dia leaves nearly a second at the start)."""
    hop = int(SR * 0.01)
    n = len(a) // hop
    e = np.array([np.sqrt((a[i * hop:(i + 1) * hop] ** 2).mean()) for i in range(n)])
    loud = np.where(e > max(e.max() * 0.03, 1e-4))[0]
    if len(loud) == 0:
        return a
    s = max(0, int((loud[0] * 0.01 - pad) * SR))
    t = min(len(a), int(((loud[-1] + 1) * 0.01 + pad) * SR))
    return a[s:t]


def _words(t):
    return re.sub(r"[^a-z0-9' ]", " ", t.lower().replace("-", " ")).split()


def longest_gap(a):
    """Seconds of the longest silence inside the take (Dia sometimes stalls in the middle and then runs out of room before the end)."""
    hop = int(SR * 0.02)
    n = len(a) // hop
    e = np.array([np.sqrt((a[i * hop:(i + 1) * hop] ** 2).mean()) for i in range(n)])
    quiet, best, run = e < max(e.max() * 0.03, 1e-4), 0, 0
    for q in quiet:
        run = run + 1 if q else 0
        best = max(best, run)
    return best * 0.02


def judge(text, a):
    """(word match 0..1, voice similarity 0..1, [[start, end, word]]) for one take; all zero if the pace is not speech,
    there is a long silence inside, or the last words of the text are not at the end of what was spoken."""
    want = _words(text)
    if not 1.8 <= len(want) / max(len(a) / SR, 0.1) <= 5.2 or longest_gap(a) > 1.5:
        return 0.0, 0.0, []
    a16 = torchaudio.functional.resample(torch.from_numpy(a), SR, 16000).numpy()  # faster-whisper wants 16 kHz
    segs, _ = state["asr"].transcribe(a16, language="en", word_timestamps=True)
    heard = [w for s in segs for w in s.words]
    said = _words(" ".join(w.word for w in heard))
    match = difflib.SequenceMatcher(None, want, said).ratio()
    if want[-3:] != said[-3:] and want[-2:] != said[-3:-1]:  # cut off before the end
        return 0.0, 0.0, []
    voice = float(np.dot(state["ref_emb"], state["enc"].embed_utterance(preprocess_wav(a, source_sr=SR))))
    return match, voice, [[round(float(w.start), 3), round(float(w.end), 3), w.word.strip()] for w in heard]


def speak(text):
    text = " ".join(text.split())
    best = None  # (rank, audio, match, voice, words)
    for seed in SEEDS:
        with lock:
            torch.manual_seed(seed)
            a = state["model"].generate(f"{state['ref_txt']} [S1] {text}", audio_prompt=state["prompt"], use_torch_compile=False, verbose=False, max_tokens=3072)
        a = np.asarray(a, dtype=np.float32)
        if a.size < SR // 2:
            continue
        a = trim(a)
        match, voice, words = judge(text, a)
        print(f"seed {seed}: {len(a) / SR:.1f}s words {match:.2f} voice {voice:.2f}", flush=True)
        rank = min(match / MIN_MATCH, 1) + min(voice / MIN_VOICE, 1)
        if best is None or rank > best[0]:
            best = (rank, a, match, voice, words)
        if match >= MIN_MATCH and voice >= MIN_VOICE:
            break
    if best is None or best[2] < FLOOR_MATCH or best[3] < FLOOR_VOICE:
        raise RuntimeError("Dia could not speak this cleanly in the saved voice" + (f" (best: words {best[2]:.2f}, voice {best[3]:.2f})" if best else ""))
    buf = io.BytesIO()
    sf.write(buf, best[1], SR, format="WAV")
    return buf.getvalue(), best[4], best[2], best[3]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/plain", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health" and "model" in state:
            return self._send(200, b"ok")
        self._send(503, b"loading")

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            text = str(body.get("text", "")).strip()
            if not text:
                return self._send(400, b"no text")
            wav, words, match, voice = speak(text)
            self._send(200, wav, "audio/wav", {"X-Words": json.dumps(words), "X-Match": f"{match:.2f}", "X-Voice": f"{voice:.2f}"})
        except Exception as e:  # report to the caller instead of dropping the connection
            self._send(500, str(e)[:300].encode())


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    load()
    threading.Event().wait()
