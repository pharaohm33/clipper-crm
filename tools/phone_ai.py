#!/usr/bin/env python3
"""
Last resort phone finder: ask Google AI Mode (in the shared Chrome window) for the public business number of leads whose own pages show none.

    python3 tools/phone_ai.py leads.json        # [{"id","name","url","web"}, ...]

Prints one 'PHONEAI {json}' line per lead. The AI must name the show it is answering about (so a mixed up page can never give a lead another lead's number),
the number must look like a real US/Canada number, and the answer must say where it saw it. These numbers are marked as coming from Google AI, because AI
can be wrong: the CRM tells you to confirm the number when you call.
"""
import difflib
import json
import random
import re
import sys
import time

import ai_browser as AB
import google_ai_to_crm as G
import phone_finder as P


DEFAULT_TEMPLATE = ("Find the public business phone number for {who} ({where}). Only give a number you can actually see on an official page, such as their website, "
                    "their Google business listing or their social profile. Do not guess and do not use people-search sites, and say unknown if you cannot find one.")
JSON_TAIL = (" End your answer with exactly one line of JSON with these keys: show (must be exactly \"{name}\"), phone (the number, or empty), "
             "where (a short note on where it is listed), confidence (a number from 0 to 1).")


def build_prompt(l, template=None):
    """The wording comes from the CRM (editable in the Calls tab). {who} {owner} {business} {name} {where} are filled in; the JSON answer line is always added if missing."""
    where = f"website {l['web']}" if l.get("web") else f"YouTube channel {l.get('url')}"
    owner, biz = (l.get("owner") or "").strip(), (l.get("business") or "").strip()
    who = f"the YouTube channel owner {owner}" if owner else f"the owner of the YouTube channel \"{l.get('name')}\""
    if biz:
        who += f", who owns {biz}"
    text = (template or DEFAULT_TEMPLATE)
    for k, v in (("who", who), ("owner", owner or l.get("name") or ""), ("business", biz or l.get("name") or ""), ("name", l.get("name") or ""), ("where", where)):
        text = text.replace("{" + k + "}", str(v))
    if '"phone"' not in text:
        text = text.rstrip() + JSON_TAIL.replace("{name}", str(l.get("name") or ""))
    return text


def same_show(a, b):
    norm = lambda s: re.sub(r"[^a-z0-9 ]", "", str(s or "").lower()).strip()
    a, b = norm(a), norm(b)
    return bool(a and b) and (a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.55)


def parse(text, name=""):
    """The last JSON object that is about this lead, with a believable number and a stated source. None otherwise."""
    best = None
    for m in re.finditer(r"\{[^{}]*\"phone\"[^{}]*\}", text or "", re.S):
        try:
            o = json.loads(re.sub(r",\s*}", "}", m.group(0)))
        except Exception:
            continue
        if name and not same_show(o.get("show"), name):
            continue
        found = P.extract(" call " + str(o.get("phone") or ""))  # the word makes the number count, the plausibility rules still apply
        if not found or not str(o.get("where") or "").strip():
            continue
        try:
            conf = float(o.get("confidence") or 0)
        except Exception:
            conf = 0
        if conf < 0.6:
            continue
        best = {"phone": found[0]["number"], "kind": found[0]["kind"], "where": str(o["where"])[:140], "confidence": conf}
    return best


def main():
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    leads, template = (data["leads"], data.get("template")) if isinstance(data, dict) else (data, None)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, ctx, page = AB.get_page(p)
        for n, l in enumerate(leads):
            print(f"[{n + 1}/{len(leads)}] asking Google AI for {l.get('name')}'s business phone ...")
            data = G.ask_google_ai(page, build_prompt(l, template))
            o = parse((data or {}).get("text", ""), l.get("name"))
            print("PHONEAI " + json.dumps({"id": l["id"], **(o or {"unchecked": True})}))
            if n < len(leads) - 1:
                time.sleep(random.uniform(8, 16))
        AB.release(browser)
    print("Done.")


if __name__ == "__main__":
    main()
