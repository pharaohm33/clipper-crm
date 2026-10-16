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
import email_check
import phone_finder
import ai_browser as AB
import email_ai
import google_ai_to_crm as G
from phone_ai import same_show


DEFAULT_TEMPLATE = ("Who is the founder, owner or head of marketing or e-commerce at {company} ({website}), the person who decides how much to spend on advertising? "
                    "Give me their email address and phone number.")
JSON_TAIL = (" End your answer with exactly one line of JSON with these keys: company (the exact company name you answered about), person (full name, or empty), "
             "title (their role), email (their email address, or empty), phone (their phone number, or empty), "
             "linkedin_url (their linkedin.com/in address, or empty), "
             "where (a short note on where this is stated), confidence (a number from 0 to 1).")


def build_prompt(l, template=None):
    """The wording is editable in the CRM. {company} {website} {facebook} are filled in; the JSON answer line is added if the template leaves it out."""
    text = template or DEFAULT_TEMPLATE
    for k, v in (("company", l.get("company") or ""), ("website", l.get("web") or "no website"), ("facebook", l.get("facebook") or "")):
        text = text.replace("{" + k + "}", str(v))
    if '"person"' not in text:
        text = text.rstrip() + JSON_TAIL
    return text


def parse_person(text, company, web=""):
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
        li = re.search(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+", str(o.get("linkedin_url") or ""))
        best = {"person": name, "title": str(o.get("title") or "")[:80], "where": str(o["where"])[:140], "confidence": conf, "linkedin": li.group(0) if li else ""}
        addr = str(o.get("email") or "").strip().lower()
        if email_ai.EMAIL_RE.fullmatch(addr) and email_check.classify(addr)["ok"] and (not web or own_domain(addr, web)):
            best["email"] = addr
        found = phone_finder.extract(" call " + str(o.get("phone") or ""))
        if found:
            best["phone"] = found[0]["number"]
            best["phone_kind"] = found[0]["kind"]
    return best


def own_domain(addr, web):
    host = (urllib.parse.urlparse(web if str(web).startswith("http") else "https://" + str(web)).hostname or "")
    root = ad_leads._root(host)
    dom = addr.split("@")[-1]
    return ad_leads._root(dom) == root or root.split(".")[0][:5] in dom


def main():
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    leads, template = (data["leads"], data.get("template")) if isinstance(data, dict) else (data, None)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, ctx, page = AB.get_page(p)
        for n, l in enumerate(leads):
            print(f"[{n + 1}/{len(leads)}] asking Google AI who decides on ads at {l['company']} ...")
            ans = G.ask_google_ai(page, build_prompt(l, template))
            o = parse_person((ans or {}).get("text", ""), l["company"], l.get("web", ""))
            out = {"id": l["id"], **(o or {"none": True})}
            try:  # the company's own pages: emails (one matching the name if there is one) and phone numbers
                c = ad_leads.contacts(l.get("web", ""), out.get("person", ""))
                out["site_emails"] = [e["email"] for e in c["emails"]][:4]
                if c["person_email"] and not out.get("email"):
                    out["email"] = c["person_email"]
                out["phones"] = [p["phone"] for p in c["phones"]]
            except Exception:
                pass
            print("DMAKER " + json.dumps(out))
            if n < len(leads) - 1:
                time.sleep(random.uniform(8, 16))
        AB.release(browser)
    print("Done.")


if __name__ == "__main__":
    main()
