#!/usr/bin/env python3
"""
Instagram accounts for outreach targets, asked of Google AI Mode (in the shared Chrome window).

    python3 tools/ig_finder_ai.py leads.json     # {"template": "...optional...", "leads": [{"id","company","web","person","title"}]}

Prints one 'IGAI {json}' line per lead: person_handle and/or brand_handle, where it was seen, confidence. A handle is accepted only when the answer names the same
company, says where it was seen, the handle is well formed, and Instagram does not answer "not found" for it. These are SUGGESTIONS to check by eye before use:
profile pages sit behind a login wall, so a handle can exist and still belong to someone else.
"""
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request

import ai_browser as AB
import google_ai_to_crm as G
from phone_ai import same_show

DEFAULT_TEMPLATE = ("What are the Instagram accounts for {who}? I need the personal Instagram handle of the person, and the company's own Instagram handle.")
JSON_TAIL = (" End your answer with exactly one line of JSON with these keys: company (the exact company name you answered about), person_handle (their personal handle, or empty), "
             "brand_handle (the company's handle, or empty), where (a short note on where this is stated), confidence (a number from 0 to 1).")
HANDLE = re.compile(r"^[A-Za-z0-9._]{2,30}$")
GENERIC = {"instagram", "explore", "accounts", "reel", "reels", "stories", "p", "tv", "direct", "about", "legal", "unknown", "none", "n/a"}


def build_prompt(l, template=None):
    who = (f"{l['person']} ({l.get('title') or 'owner'} of {l['company']}, {l.get('web') or 'no website'})" if l.get("person")
           else f"{l['company']} ({l.get('web') or 'no website'})")
    text = template or DEFAULT_TEMPLATE
    for k, v in (("who", who), ("company", l.get("company") or ""), ("website", l.get("web") or ""), ("person", l.get("person") or ""), ("title", l.get("title") or "")):
        text = text.replace("{" + k + "}", str(v))
    if '"person_handle"' not in text:
        text = text.rstrip() + JSON_TAIL
    return text


def clean_handle(raw):
    h = str(raw or "").strip()
    m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", h)
    h = (m.group(1) if m else h).lstrip("@").strip("/ ").strip(".")
    return h if HANDLE.match(h) and h.lower() not in GENERIC else ""


def exists(handle):
    """False only when Instagram clearly answers 404 for the profile. Anything else (login wall, rate limit, network) counts as 'cannot tell'."""
    try:
        req = urllib.request.Request(f"https://www.instagram.com/{handle}/", headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36"})
        urllib.request.urlopen(req, timeout=10).read(2000)
        return True
    except urllib.error.HTTPError as e:
        return e.code != 404
    except Exception:
        return True


def parse(text, company=""):
    best = None
    for m in re.finditer(r"\{[^{}]*\"person_handle\"[^{}]*\}", text or "", re.S):
        try:
            o = json.loads(re.sub(r",\s*}", "}", m.group(0)))
        except Exception:
            continue
        if company and not same_show(o.get("company"), company):
            continue
        try:
            conf = float(o.get("confidence") or 0)
        except Exception:
            conf = 0
        if conf < 0.6 or not str(o.get("where") or "").strip():
            continue
        ph, bh = clean_handle(o.get("person_handle")), clean_handle(o.get("brand_handle"))
        if ph and not exists(ph):
            ph = ""
        if bh and not exists(bh):
            bh = ""
        if ph or bh:
            best = {"person_handle": ph, "brand_handle": bh, "where": str(o["where"])[:140], "confidence": conf}
    return best


def main():
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    leads, template = (data["leads"], data.get("template")) if isinstance(data, dict) else (data, None)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        sess = AB.Session(p)
        for n, l in enumerate(leads):
            print(f"[{n + 1}/{len(leads)}] asking Google AI for {l['company']}'s Instagram ...")
            ans = sess.ask(G.ask_google_ai, build_prompt(l, template))
            o = parse((ans or {}).get("text", ""), l["company"])
            print("IGAI " + json.dumps({"id": l["id"], **(o or {"none": True})}))
            if n < len(leads) - 1:
                time.sleep(random.uniform(8, 16))
        sess.release()
    print("Done.")


if __name__ == "__main__":
    main()
