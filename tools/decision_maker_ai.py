#!/usr/bin/env python3
"""
Who decides on advertising at a company? Asks Google AI Mode (in the shared Chrome window), then, if a name comes back, asks for that person's public work email.

    python3 tools/decision_maker_ai.py leads.json     # [{"id","company","web","facebook"}, ...]

Prints one 'DMAKER {json}' line per lead: person, title, where (where it was seen), and email (only when it was seen on an official page
and sits on the company's own domain). Business information only: no people-search sites, no guessing an address from a name.
"""
import json
import random
import re
import sys
import time
import urllib.parse

import ad_leads
import ai_browser as AB
import email_ai
import google_ai_to_crm as G
from phone_ai import same_show


def who_prompt(l):
    site = f" ({l['web']})" if l.get("web") else ""
    return (f"Who is the founder, owner or head of marketing or e-commerce at {l['company']}{site}, the person who decides how much to spend on advertising? "
            "Use only official sources: the company website (about, team or press pages), the company's own social pages, news articles and interviews. "
            "Do not use people-search sites, do not guess, and say unknown if you are not sure. "
            "End your answer with exactly one line of JSON with these keys: company (the exact company name you answered about), person (full name, or empty), "
            "title (their role), where (a short note on where it is stated), confidence (a number from 0 to 1).")


def mail_prompt(l, person):
    return (f"What is the public work email address of {person} at {l['company']} ({l.get('web') or ''})? Only give an address you can see written on an official page "
            "such as the company website, a press page or their own profile, never one guessed from a name pattern, and not from people-search or email lookup sites. "
            "Say unknown if you cannot find one. End your answer with exactly one line of JSON with these keys: "
            f"show (must be exactly \"{l['company']}\"), email (the address, or empty), where (a short note on where it is listed), confidence (a number from 0 to 1).")


def parse_person(text, company):
    best = None
    for m in re.finditer(r"\{[^{}]*\"person\"[^{}]*\}", text or "", re.S):
        try:
            o = json.loads(re.sub(r",\s*}", "}", m.group(0)))
        except Exception:
            continue
        if not same_show(o.get("company"), company):
            continue
        name = re.sub(r"\s+", " ", str(o.get("person") or "")).strip()
        try:
            conf = float(o.get("confidence") or 0)
        except Exception:
            conf = 0
        if len(name.split()) < 2 or len(name) > 60 or not str(o.get("where") or "").strip() or conf < 0.6 or re.search(r"unknown|n/a|none", name, re.I):
            continue
        best = {"person": name, "title": str(o.get("title") or "")[:80], "where": str(o["where"])[:140], "confidence": conf}
    return best


def own_domain(addr, web):
    host = (urllib.parse.urlparse(web if str(web).startswith("http") else "https://" + str(web)).hostname or "")
    root = ad_leads._root(host)
    dom = addr.split("@")[-1]
    return ad_leads._root(dom) == root or root.split(".")[0][:5] in dom


def main():
    leads = json.load(open(sys.argv[1], encoding="utf-8"))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, ctx, page = AB.get_page(p)
        for n, l in enumerate(leads):
            print(f"[{n + 1}/{len(leads)}] asking Google AI who decides on ads at {l['company']} ...")
            data = G.ask_google_ai(page, who_prompt(l))
            o = parse_person((data or {}).get("text", ""), l["company"])
            out = {"id": l["id"], **(o or {"none": True})}
            if o:
                time.sleep(random.uniform(6, 12))
                d2 = G.ask_google_ai(page, mail_prompt(l, o["person"]))
                e = email_ai.parse((d2 or {}).get("text", ""), l["company"])
                if e and own_domain(e["email"], l.get("web", "")):
                    out.update(email=e["email"], email_quality=e["quality"], email_where=e["where"])
            print("DMAKER " + json.dumps(out))
            if n < len(leads) - 1:
                time.sleep(random.uniform(8, 16))
        AB.release(browser)
    print("Done.")


if __name__ == "__main__":
    main()
