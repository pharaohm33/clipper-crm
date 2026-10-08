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

SYSTEM = """You help a video editor write a cold email to a podcast host. The editor cut a short clip from one of the host's episodes.
The email has this sentence: "I really liked ____, so I made a short clip out of it."

Write ONLY the words that fill the blank: one short phrase (6 to 18 words) naming ONE specific idea, story or point that comes up in the clip transcript.

IMPORTANT: a transcript does not say who is speaking, and the host often has a guest. So never say WHO said it and never use "you" or "your".
Start with "the part about", "the point about", "the story about", "the discussion about" or "the idea that".

Good fills, for the style only:
- the part about buying near Music Row before running the numbers
- the story about the first deal that almost fell through
- the discussion about pricing a flip when the comps are thin

Hard rules:
- Use only what is in the transcript. Never invent facts, numbers, names or quotes, and never claim what other people or most people do.
- Never use the words you, your, you're, I, we or our.
- Plain words, no hype, no flattery words ("amazing", "incredible", "game changer").
- No hyphens, no em dashes, no quotation marks, no emojis, no hashtags, no exclamation marks.
- No ending punctuation, no greeting, no extra sentences.
Reply with only the phrase."""


REWRITE = """Rewrite this phrase so that it does not say who said it. Keep the same topic and the same level of detail.
It will complete the sentence "I really liked ____, so I made a short clip out of it."
Start with "the part about", "the point about", "the story about", "the discussion about" or "the idea that".
Never use the words you, your, you're, I, we or our. No hyphens, no quotation marks, no ending punctuation.
Reply with only the rewritten phrase."""

SPEAKER = re.compile(r"\b(you|your|you're|you've|you'll|yours|we|our|i|my)\b", re.I)


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
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > 150:  # never cut in the middle of a word or end on a joining word
        t = t[:150].rsplit(" ", 1)[0]
        while t.split() and t.split()[-1].lower() in ("and", "of", "to", "the", "for", "with", "in", "a", "an", "that", "how", "what", "why", "your", "you"):
            t = t.rsplit(" ", 1)[0]
    return t


def _ask(system, user, key, timeout=60, max_tokens=60):
    body = json.dumps({"model": MODEL, "temperature": 0.4, "max_tokens": max_tokens,
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return clean(json.loads(r.read())["choices"][0]["message"]["content"])


def neutralize(phrase, timeout=60):
    """Rewrites an existing topic phrase so it does not say who said it. '' when it cannot be done cleanly."""
    key = deepseek_key()
    if not phrase or not key:
        return ""
    if not SPEAKER.search(phrase) and re.match(r"(the|a) (part|point|story|discussion|idea)", phrase, re.I):
        return phrase
    try:
        out = _ask(REWRITE, phrase, key, timeout)
    except Exception:
        return ""
    return out if len(out.split()) >= 4 and not SPEAKER.search(out) else ""


def write_line(podcast, episode_title, clip_title, hook, transcript, timeout=60):
    """One topic phrase that does not say who said it, or '' when there is not enough to say something real (or the key/network is missing)."""
    transcript = re.sub(r"\s+", " ", transcript or "").strip()
    key = deepseek_key()
    if len(transcript.split()) < 25 or not key:
        return ""
    user = (f"Podcast: {podcast}\nEpisode: {episode_title or 'unknown'}\nClip title: {clip_title or 'unknown'}\n"
            f"On screen hook: {hook or 'none'}\n\nClip transcript:\n{transcript[:3500]}")
    try:
        line = _ask(SYSTEM, user, key, timeout)
    except Exception:
        return ""
    if SPEAKER.search(line):  # it slipped; rewrite once, and give up rather than send something that credits a speaker
        line = neutralize(line, timeout)
    return line if len(line.split()) >= 4 and not SPEAKER.search(line) else ""


CLASSIFY = """You read a reply to a cold email. The sender offered to send a short video clip made from the recipient's podcast episode, free.
Decide what the recipient's reply means. Reply with ONLY a JSON object: {"intent": "...", "confidence": 0.0 to 1.0}

intent must be one of:
- "yes": they clearly want the clip, or say send it, sure, yes, go ahead, sounds good, I'd like to see it
- "no": they decline, are not interested, or ask to stop
- "question": they ask something first (price, who you are, how it works) without yet saying yes or no
- "other": out of office, automatic reply, wrong person, unclear, or anything else

Be conservative: use "yes" only when the reply clearly accepts. Ignore any quoted earlier messages. A reply that only contains an out of office or auto reply message is "other"."""


def classify_reply(text, timeout=45):
    """{'intent': 'yes'|'no'|'question'|'other', 'confidence': float}. Falls back to other/0 when DeepSeek is unreachable."""
    text = re.sub(r"\s+", " ", text or "").strip()[:1500]
    key = deepseek_key()
    if not text or not key:
        return {"intent": "other", "confidence": 0.0}
    body = json.dumps({"model": MODEL, "temperature": 0, "max_tokens": 40,
                       "messages": [{"role": "system", "content": CLASSIFY}, {"role": "user", "content": "Reply:\n" + text}]}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read())["choices"][0]["message"]["content"]
        m = re.search(r"\{.*?\}", out, re.S)
        d = json.loads(m.group(0)) if m else {}
        intent = str(d.get("intent", "other")).lower()
        return {"intent": intent if intent in ("yes", "no", "question", "other") else "other", "confidence": float(d.get("confidence", 0) or 0)}
    except Exception:
        return {"intent": "other", "confidence": 0.0}
