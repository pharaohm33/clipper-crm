#!/usr/bin/env python3
"""
Writes the short phrase that completes \"I really liked ____\" in the cold email, using DeepSeek.
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

SYSTEM = """You help a video editor write a cold email to a podcast host. The editor cut a short clip from the host's own episode.
The email has this sentence: "I really liked ____, so I made a short clip out of it."

Write ONLY the words that fill the blank: one short phrase (6 to 18 words) naming ONE specific idea, story or point the host makes in the clip transcript.

Good fills, for the style only:
- the part where you explain why you bought near Music Row before running the numbers
- your story about the first deal that almost fell through
- how you describe pricing a flip when the comps are thin

Hard rules:
- Use only what is in the transcript. Never invent facts, numbers, names or quotes, and never claim what other people or most people do.
- Start with "the part where you", "your story about", "your point about", "how you" or "your take on".
- Plain words, no hype, no flattery words ("amazing", "incredible", "game changer").
- No hyphens, no em dashes, no quotation marks, no emojis, no hashtags, no exclamation marks.
- No ending punctuation, no greeting, no extra sentences.
Reply with only the phrase."""


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
    t = re.sub(r"\s+", " ", (text or "").strip().strip("\"'`“”")).rstrip(".,;:")
    t = re.sub(r"\s*[—–]\s*", ", ", t).replace("-", " ").replace("!", ".")
    t = re.sub(r"[{}|]", "", t)
    return re.sub(r"\s+", " ", t).strip()[:160]


def write_line(podcast, episode_title, clip_title, hook, transcript, timeout=60):
    """One personalized note, or '' when there is not enough to say something real (or the key/network is missing)."""
    transcript = re.sub(r"\s+", " ", transcript or "").strip()
    key = deepseek_key()
    if len(transcript.split()) < 25 or not key:
        return ""
    user = (f"Podcast: {podcast}\nEpisode: {episode_title or 'unknown'}\nClip title: {clip_title or 'unknown'}\n"
            f"On screen hook: {hook or 'none'}\n\nClip transcript:\n{transcript[:3500]}")
    body = json.dumps({"model": MODEL, "temperature": 0.6, "max_tokens": 60,
                       "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read())["choices"][0]["message"]["content"]
    except Exception:
        return ""
    line = clean(out)
    return line if len(line.split()) >= 4 else ""
