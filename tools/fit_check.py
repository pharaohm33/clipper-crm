#!/usr/bin/env python3
"""
Fit check through Google AI Mode in Chrome (no API key and no quota): is each lead a small, owner led business that can decide alone and pay?

    python3 tools/fit_check.py leads.json        # leads.json = [{"id","name","url","web","subs"}, ...]

Prints one 'FIT {json}' line per lead for the CRM to read. Uses the same separate Chrome profile as google_ai_to_crm.py, so a
Google verification you solved before usually does not come back. If Google asks again, solve it in the window.
"""
import difflib
import json
import random
import re
import sys
import time

import ai_browser as AB
import google_ai_to_crm as G

DECIDERS = {"owner", "team", "corporate", "unknown"}


def build_prompt(l):
    return (f"Is the YouTube show \"{l.get('name')}\" ({l.get('url')}{', website ' + l['web'] if l.get('web') else ''}) run by a small independent owner who could decide alone "
            "to pay a freelancer $300 to $1,000 a month for short form video clips? Big company signs (bad fit): a franchise or national or global brand, owned by or part of a larger "
            "media company or network, a corporate marketing department, about 50 or more employees, publicly traded, or the host is an employee and not the owner. Good fit signs: the host "
            "is the owner, a solo person or small team, their own agency, practice, brokerage, builder, coaching business or product. Affordability signs: sponsors, paid products or programs, "
            "several revenue streams. Do not guess, say unknown when you cannot find it. End your answer with exactly one line of JSON with these keys: "
            "show (the exact show name you are answering about), decider (owner, team, corporate or unknown), size (solo, small, mid, large or unknown), big_company (true or false), can_afford (yes, maybe, no or unknown), "
            "reasons (a list of up to 3 short strings), confidence (a number from 0 to 1).")


def same_show(a, b):
    norm = lambda s: re.sub(r"[^a-z0-9 ]", "", str(s or "").lower()).strip()
    a, b = norm(a), norm(b)
    return bool(a and b) and (a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.55)


def parse(text, name=""):
    """The last JSON object in the answer that has real values AND is about this lead. (The echoed question holds a template full of | bars,
    which is skipped, and if the page ever holds answers for two leads, only the one that names this show is used.)"""
    found = None
    for m in re.finditer(r"\{[^{}]*\"decider\"[^{}]*\}", text or "", re.S):
        try:
            o = json.loads(re.sub(r",\s*}", "}", m.group(0)))
        except Exception:
            continue
        if str(o.get("decider", "")).lower() not in DECIDERS:
            continue
        if name and not same_show(o.get("show"), name):
            continue
        found = o
    return found


def main():
    leads = json.load(open(sys.argv[1], encoding="utf-8"))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, ctx, page = AB.get_page(p)
        for n, l in enumerate(leads):
            print(f"[{n + 1}/{len(leads)}] checking {l.get('name')} with Google AI ...")
            data = G.ask_google_ai(page, build_prompt(l))
            o = parse((data or {}).get("text", ""), l.get("name"))
            if not o:
                print("  no usable answer, leaving this lead unchecked")
                print("FIT " + json.dumps({"id": l["id"], "unchecked": True}))
            else:
                o["id"] = l["id"]
                print("FIT " + json.dumps(o))
            if n < len(leads) - 1:
                time.sleep(random.uniform(8, 16))
        AB.release(browser)
    print("Done.")


if __name__ == "__main__":
    main()
