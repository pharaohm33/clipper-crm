#!/usr/bin/env python3
"""
Writes one specific, honest sentence or two about the clip we made from a podcast's episode, using DeepSeek.
The line is built ONLY from the clip's own transcript, so it can point at something the host really said.

The DeepSeek key is read (never printed) from, in order: the DEEPSEEK_API_KEY environment variable, tools/.env,
or the video generator's .env (REPO/.env).
"""
import json
import os
import re
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.getenv("CLIPPER_REPO") or Path.home() / "instagram-video-generator")
URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

SYSTEM = """You write one short personal note inside a cold email from a video editor to a podcast host.
The editor cut a short clip from the host's own episode and is giving it to them for free.

Write 1 or 2 plain sentences (at most 45 words) that:
- point to ONE specific idea, story or point the host actually makes in the clip transcript, in your own words
- say why that moment works as a short clip (for example it is a complete thought, a surprising detail, or a strong opinion)
- sound like a real person wrote it quickly: warm, specific, no hype

Hard rules:
- Use only what is in the transcript. Never invent facts, numbers, names or quotes, and never claim what other people or most people do. Do not quote more than 5 words in a row.
- No flattery clichés ("amazing", "incredible", "game changer", "love your content").
- Do not mention AI, transcripts, or that you are summarizing.
- No hyphens, no em dashes, no emojis, no hashtags, no exclamation marks.
- Do not greet and do not end with a question or a call to action.
Reply with only the sentences."""


def deepseek_key():
    k = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if k:
        return k
    for f in (HERE / ".env", REPO / ".env"):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                m = re.match(r"\s*DEEPSEEK_API_KEY\s*=\s*(.+?)\s*$", line)
                if m:
                    return m.group(1).strip().strip("'\"")
        except Exception:
            continue
    return ""


def clean(text):
    """Keeps the note plain: no quotes around it, no dashes, no braces or pipes (those mean spintax in the email engine)."""
    t = re.sub(r"\s+", " ", (text or "").strip().strip("\"'`“”"))
    t = re.sub(r"\s*[—–]\s*", ", ", t).replace("-", " ").replace("!", ".")
    t = re.sub(r"[{}|]", "", t)
    return re.sub(r"\s+", " ", t).strip()[:320]


def write_line(podcast, episode_title, clip_title, hook, transcript, timeout=60):
    """One personalized note, or '' when there is not enough to say something real (or the key/network is missing)."""
    transcript = re.sub(r"\s+", " ", transcript or "").strip()
    key = deepseek_key()
    if len(transcript.split()) < 25 or not key:
        return ""
    user = (f"Podcast: {podcast}\nEpisode: {episode_title or 'unknown'}\nClip title: {clip_title or 'unknown'}\n"
            f"On screen hook: {hook or 'none'}\n\nClip transcript:\n{transcript[:3500]}")
    body = json.dumps({"model": MODEL, "temperature": 0.6, "max_tokens": 120,
                       "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read())["choices"][0]["message"]["content"]
    except Exception:
        return ""
    line = clean(out)
    return line if 20 <= len(line) else ""
