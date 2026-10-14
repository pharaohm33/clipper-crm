#!/usr/bin/env python3
"""
Finds independent coaches (fitness, weight loss, executive) and their PUBLIC business contact details, with no LinkedIn login:

    python3 tools/coach_finder.py discover job.json     # {"label","location","count","exclude":[hosts]}  -> one 'COACH {json}' line per verified coach
    python3 tools/coach_finder.py contacts "https://their-site.com"

How it stays honest:
  * Google AI Mode (the shared Chrome window) only SUGGESTS names and websites. Nothing it says about an email or phone is used.
  * A suggestion is kept only if the website loads, talks about coaching, and shows the coach's or business's own name.
  * The email and phone come only from that website's own pages (mailto/tel links, structured data, numbers next to words like call or text).
    Emails are checked for syntax, disposable domains and a real mail server. Nothing is guessed (no info@ patterns).
  * A phone is marked "mobile" only when the page itself calls it a cell, mobile or text number. A phone number alone can't tell a mobile
    from a landline, so treat unmarked numbers as "business line", and check the National Do Not Call list before calling or texting.
"""
import json
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import email_finder as EF
import phone_finder as PF

COACH_WORDS = re.compile(r"coach|coaching|personal train|trainer|mentor|consult", re.I)
SKIP_HOSTS = re.compile(r"(linkedin|facebook|instagram|twitter|x\.com|youtube|tiktok|yelp|psychologytoday|trainerize|thumbtack|expertise\.com|"
                        r"indeed|glassdoor|wikipedia|amazon|eventbrite|meetup|reddit|pinterest|medium\.com|substack|linktr\.ee|calendly|"
                        r"google\.|bing\.|forbes|inc\.com|coach\.com|noomii|bark\.com|nerdwallet|healthline)", re.I)
GENERIC = {"coach", "coaching", "fitness", "wellness", "health", "life", "executive", "weight", "loss", "the", "and", "llc", "inc", "co", "with", "training",
           "personal", "online", "leadership", "business", "group", "solutions", "consulting", "performance", "strength", "nutrition"}


def origin(site):
    site = (site or "").strip()
    if not site:
        return ""
    if not re.match(r"https?://", site, re.I):
        site = "https://" + site
    u = urllib.parse.urlparse(site)
    return f"{u.scheme}://{u.netloc.lower()}" if u.netloc and "." in u.netloc else ""


def host(site):
    return urllib.parse.urlparse(origin(site)).netloc.replace("www.", "")


def build_prompt(label, location, count, exclude):
    where = f" based in {location}" if location else " in the United States"
    skip = f" Skip these websites: {', '.join(exclude[:25])}." if exclude else ""
    return (f"Use Google Search. Find {count} real independent {label}s{where} who run their own coaching business and have their own website "
            f"(not a big gym chain, not a directory or listing page, not a large company).{skip} "
            "End your answer with one line per coach, each line exactly one JSON object with keys: "
            "name (the coach's full name), business (their business name), website (their own website address), location (city and state), "
            "who (one short phrase on who they coach). No other text on those lines.")


def parse_list(text):
    """The coach objects in an AI answer (any JSON object with a website). Each needs a name and a usable website."""
    out, seen = [], set()
    for m in re.finditer(r"\{[^{}]*\"website\"[^{}]*\}", text or "", re.S):
        try:
            o = json.loads(re.sub(r",\s*}", "}", m.group(0)))
        except Exception:
            continue
        site = origin(o.get("website"))
        if not site or SKIP_HOSTS.search(host(site)) or not str(o.get("name") or "").strip() or host(site) in seen:
            continue
        seen.add(host(site))
        out.append({"name": str(o["name"]).strip()[:80], "business": str(o.get("business") or "").strip()[:80], "website": site,
                    "location": str(o.get("location") or "")[:60], "who": str(o.get("who") or "")[:100]})
    return out


def _fetch(site):
    try:
        return EF._get(site, 600_000, 10)
    except Exception:
        return ""


def about(html):
    m = re.search(r"<meta[^>]+(?:name|property)=[\"'](?:og:)?description[\"'][^>]+content=[\"']([^\"']{20,300})", html or "", re.I) or \
        re.search(r"<meta[^>]+content=[\"']([^\"']{20,300})[\"'][^>]+(?:name|property)=[\"'](?:og:)?description[\"']", html or "", re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def site_ok(c, html):
    """True when the page is real, about coaching, and shows the coach's or business's own name (so a made up or mixed up answer is dropped)."""
    if not html or not COACH_WORDS.search(html):
        return False
    text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S | re.I).lower()
    toks = {t for t in re.findall(r"[a-z0-9]+", c["business"].lower()) if len(t) > 2 and t not in GENERIC}
    last = (re.findall(r"[a-z]+", c["name"].lower()) or [""])[-1]
    if len(last) > 2:
        toks.add(last)
    return any(t in text for t in toks)


def contacts(site):
    """{'email','email_quality','phone','phone_mobile','phone_how','others'} from the website's own pages. Empty values when nothing believable."""
    out = {"email": "", "phone": "", "phone_mobile": False, "phone_how": "", "others": []}
    try:
        emails = EF.from_website(site)
        hit = EF._pick(emails, "their website") if emails else None
        if hit:
            out.update(email=hit["email"], email_quality=hit.get("quality", ""), others=hit.get("others", []))
    except Exception:
        pass
    try:
        phones = PF.from_website(site)
        if phones:
            best = next((p for p in phones if p.get("mobile")), phones[0])  # a number the page calls a cell or text line wins
            out.update(phone=best["number"], phone_mobile=bool(best.get("mobile")), phone_how=best["how"] + (", toll free" if best["kind"] == "toll free" else ""))
    except Exception:
        pass
    return out


def enrich(c):
    """A suggestion becomes a prospect only after the site checks out. Returns None when it does not."""
    html = _fetch(c["website"])
    if not site_ok(c, html):
        return None
    return {**c, "about": about(html), **contacts(c["website"])}


def discover(job, log=print):
    import ai_browser as AB
    import google_ai_to_crm as G
    from playwright.sync_api import sync_playwright
    label, count = job.get("label") or "coach", int(job.get("count") or 8)
    prompt = build_prompt(label, job.get("location") or "", count, job.get("exclude") or [])
    with sync_playwright() as p:
        browser, ctx, page = AB.get_page(p)
        print(f"asking Google AI for {count} {label}s ...")
        data = G.ask_google_ai(page, prompt)
        AB.release(browser)
    cands = [c for c in parse_list((data or {}).get("text", "")) if host(c["website"]) not in set(job.get("exclude") or [])]
    print(f"Google AI suggested {len(cands)}; checking each website ...")
    kept = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        for c, got in zip(cands, pool.map(enrich, cands)):
            if not got:
                print(f"  dropped {c['name']} ({host(c['website'])}): the website did not check out")
                continue
            kept += 1
            print("COACH " + json.dumps(got))
    print(f"Done: kept {kept} of {len(cands)}.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    if sys.argv[1] == "discover":
        discover(json.load(open(sys.argv[2], encoding="utf-8")))
    else:
        print(json.dumps(contacts(origin(sys.argv[2])), indent=1))
