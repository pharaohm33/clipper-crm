#!/usr/bin/env python3
"""
For businesses from a Google Maps scrape: ask Google AI Mode who owns the business and whether that owner has a YouTube channel.

    python3 tools/maps_youtube.py businesses.json     # [{"id","business","web","address","category"}, ...]

Prints one 'MAPS {json}' line per business: owner, channel_url, channel_name when a real channel was found, else {"id", "none": true}.
A channel is accepted only when the answer names the same business, gives a youtube.com address, and says where it saw that.
"""
import json
import random
import re
import sys
import time

import ai_browser as AB
import google_ai_to_crm as G
from phone_ai import same_show

YT = re.compile(r"https?://(?:www\.|m\.)?youtube\.com/(?:@[\w.\-]+|channel/UC[\w\-]+|c/[\w.\-]+|user/[\w.\-]+)", re.I)


def build_prompt(b):
    bits = [b.get("business") or ""]
    if b.get("address"):
        bits.append(b["address"])
    if b.get("web"):
        bits.append(b["web"])
    return (f"Who is the owner or founder of this business: {', '.join(x for x in bits if x)}? Does that owner or the business have its own YouTube channel with videos or podcast episodes? "
            "Only use official pages (the business website, its Google listing, its social profiles, news or the YouTube channel itself). Do not use people-search sites, do not guess, and say unknown if you cannot tell. "
            "End your answer with exactly one line of JSON with these keys: business (the exact business name you answered about), owner (full name or empty), "
            "channel_url (the full youtube.com channel address or empty), channel_name, where (a short note on where you saw it), confidence (0 to 1).")


def parse(text, business=""):
    best = None
    for m in re.finditer(r"\{[^{}]*\"channel_url\"[^{}]*\}", text or "", re.S):
        try:
            o = json.loads(re.sub(r",\s*}", "}", m.group(0)))
        except Exception:
            continue
        if business and not same_show(o.get("business"), business):
            continue
        url = YT.search(str(o.get("channel_url") or ""))
        try:
            conf = float(o.get("confidence") or 0)
        except Exception:
            conf = 0
        if not url or not str(o.get("where") or "").strip() or conf < 0.6:
            continue
        best = {"owner": re.sub(r"\s+", " ", str(o.get("owner") or "")).strip()[:80], "channel_url": url.group(0),
                "channel_name": str(o.get("channel_name") or "").strip()[:120], "where": str(o["where"])[:140], "confidence": conf}
    return best


def main():
    items = json.load(open(sys.argv[1], encoding="utf-8"))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, ctx, page = AB.get_page(p)
        for n, b in enumerate(items):
            print(f"[{n + 1}/{len(items)}] asking Google AI who owns {b.get('business')} and whether they have a YouTube channel ...")
            data = G.ask_google_ai(page, build_prompt(b))
            o = parse((data or {}).get("text", ""), b.get("business"))
            print("MAPS " + json.dumps({"id": b["id"], **(o or {"none": True})}))
            if n < len(items) - 1:
                time.sleep(random.uniform(8, 16))
        AB.release(browser)
    print("Done.")


if __name__ == "__main__":
    main()
