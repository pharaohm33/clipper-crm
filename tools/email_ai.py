#!/usr/bin/env python3
"""
Last resort email finder: ask Google AI Mode (in the shared Chrome window) for the public business contact email of leads whose own pages show none.

    python3 tools/email_ai.py leads.json       # {"template": "...optional...", "leads": [{"id","name","url","web","owner","business"}]}

Prints one 'EMAILAI {json}' line per lead. The answer must name the show, give a well formed address that passes the same quality checks as every other
address (real mail server, not disposable, not a relay), and say where it was seen. Business contact emails only.
"""
import json
import random
import re
import sys
import time

import ai_browser as AB
import email_check
import google_ai_to_crm as G
from phone_ai import same_show

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
DEFAULT_TEMPLATE = ("Find the public business contact email for {who} ({where}). Only give an address you can actually see on an official page, such as their website, "
                    "their Google business listing, their YouTube About page or their social profile. Do not guess an address from a name, do not use people-search or email lookup sites, "
                    "and say unknown if you cannot find one.")
JSON_TAIL = (" End your answer with exactly one line of JSON with these keys: show (must be exactly \"{name}\"), email (the address, or empty), "
             "where (a short note on where it is listed), confidence (a number from 0 to 1).")


def build_prompt(l, template=None):
    where = f"website {l['web']}" if l.get("web") else f"YouTube channel {l.get('url')}"
    owner, biz = (l.get("owner") or "").strip(), (l.get("business") or "").strip()
    who = f"the YouTube channel owner {owner}" if owner else f"the owner of the YouTube channel \"{l.get('name')}\""
    if biz:
        who += f", who owns {biz}"
    text = template or DEFAULT_TEMPLATE
    for k, v in (("who", who), ("owner", owner or l.get("name") or ""), ("business", biz or l.get("name") or ""), ("name", l.get("name") or ""), ("where", where)):
        text = text.replace("{" + k + "}", str(v))
    if '"email"' not in text:
        text = text.rstrip() + JSON_TAIL.replace("{name}", str(l.get("name") or ""))
    return text


def parse(text, name=""):
    best = None
    for m in re.finditer(r"\{[^{}]*\"email\"[^{}]*\}", text or "", re.S):
        try:
            o = json.loads(re.sub(r",\s*}", "}", m.group(0)))
        except Exception:
            continue
        if name and not same_show(o.get("show"), name):
            continue
        found = EMAIL_RE.fullmatch(str(o.get("email") or "").strip())
        try:
            conf = float(o.get("confidence") or 0)
        except Exception:
            conf = 0
        if not found or not str(o.get("where") or "").strip() or conf < 0.6:
            continue
        addr = found.group(0).lower()
        verdict = email_check.classify(addr)
        if not verdict["ok"]:
            continue
        best = {"email": addr, "quality": verdict["level"], "where": str(o["where"])[:140], "confidence": conf}
    return best


def main():
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    leads, template = (data["leads"], data.get("template")) if isinstance(data, dict) else (data, None)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, ctx, page = AB.get_page(p)
        for n, l in enumerate(leads):
            print(f"[{n + 1}/{len(leads)}] asking Google AI for {l.get('name')}'s business email ...")
            data = G.ask_google_ai(page, build_prompt(l, template))
            o = parse((data or {}).get("text", ""), l.get("name"))
            print("EMAILAI " + json.dumps({"id": l["id"], **(o or {"none": True})}))
            if n < len(leads) - 1:
                time.sleep(random.uniform(8, 16))
        AB.release(browser)
    print("Done.")


if __name__ == "__main__":
    main()
