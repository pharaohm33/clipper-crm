#!/usr/bin/env python3
"""
Contact emails for advertisers found in the Meta Ad Library. Website only: no podcast feeds, no YouTube, no guessing.

    python3 tools/ad_leads.py https://brand.com [https://other.com ...]

Looks at the home page and the usual contact pages (including the Shopify ones), reads mailto: links and addresses written in the page,
and keeps only addresses on the brand's own domain (or a domain the brand's own page links as its company). Placeholder, platform and
tracking addresses are dropped. Personal looking addresses rank above support@ style ones.
"""
import json
import re
import sys
import urllib.parse
import urllib.request

import email_check
import phone_finder

PATHS = ["", "/pages/team", "/team", "/pages/meet-the-team", "/pages/our-story", "/our-story", "/leadership", "/pages/press", "/press", "/pages/contact", "/pages/contact-us", "/contact", "/contact-us", "/pages/about-us", "/about", "/policies/contact-information", "/pages/faq", "/pages/customer-service"]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
JUNK = re.compile(r"^(name|email|your|you|user|test|example|john|jane|yourname|youremail|someone)@|@(example|domain|email|sentry|wixpress|shopify|myshopify|squarespace|godaddy|gmail-test|yourdomain)\.|\.(png|jpg|jpeg|gif|svg|webp|css|js)$|noreply|no-reply|donotreply", re.I)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
SUPPORT = re.compile(r"^(info|support|help|hello|contact|customerservice|customercare|care|sales|service|orders|admin|team|shop|store|press|media)@", re.I)


def _http(url, timeout=10):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(600_000).decode("utf-8", "ignore")


def _root(host):
    parts = host.lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def emails_from_site(site):
    site = site if site.startswith("http") else "https://" + site
    base = site.rstrip("/")
    root = _root(urllib.parse.urlparse(base).hostname or "")
    brand = root.split(".")[0]
    found = {}
    for p in PATHS:
        try:
            html = _http(base + p)
        except Exception:
            continue
        text = urllib.parse.unquote(html)
        mail = [m.split("?")[0] for m in re.findall(r"mailto:([^\"'\s>]+)", text, re.I)]
        for e in mail + EMAIL_RE.findall(re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)):
            e = e.strip().strip(".,;:)(<>\"'").lower()
            if not EMAIL_RE.fullmatch(e) or JUNK.search(e):
                continue
            dom = e.split("@")[1]
            # the brand's own domain, or a sibling company domain that shares the brand's name (e.g. treluxecorp.com for TreLuxe)
            if _root(dom) != root and brand[:5] not in dom:
                continue
            found.setdefault(e, p or "/")
    out = []
    for e, where in found.items():
        v = email_check.classify(e)
        if not v["ok"]:
            continue
        out.append({"email": e, "kind": "support" if SUPPORT.match(e) else "person", "found_on": where})
    out.sort(key=lambda x: (x["kind"] != "person", x["email"]))
    return out


def _person_match(local, person):
    """Does an address look like it belongs to this person (michelle@, michelle.sayers@, msayers@)?"""
    parts = [re.sub(r"[^a-z]", "", p) for p in str(person).lower().split()]
    if len(parts) < 2:
        return False
    first, last = parts[0], parts[-1]
    local = re.sub(r"[^a-z]", "", local.lower())
    return local in (first, last, first + last, last + first, first[0] + last, first + last[0]) or (len(first) >= 4 and local.startswith(first))


def contacts(site, person=""):
    """{'emails': [...], 'person_email': '' or address, 'phones': [...]} from the brand's own pages only."""
    out = {"emails": emails_from_site(site), "person_email": "", "phones": []}
    for e in out["emails"]:
        if person and _person_match(e["email"].split("@")[0], person):
            out["person_email"] = e["email"]
            e["kind"] = "person (matches the name)"
    try:
        out["phones"] = [{"phone": x["number"], "how": x["how"], "kind": x["kind"]} for x in phone_finder.from_website(site)[:3]]
    except Exception:
        pass
    if not out["phones"]:  # the store style contact pages
        base = site.rstrip("/") if site.startswith("http") else "https://" + site.rstrip("/")
        seen = set()
        for p in ("/pages/contact", "/pages/contact-us", "/policies/contact-information", "/pages/about-us", "/pages/faq"):
            try:
                for x in phone_finder._from_html(_http(base + p)):
                    if x["digits"] not in seen:
                        seen.add(x["digits"])
                        out["phones"].append({"phone": x["number"], "how": x["how"], "kind": x["kind"]})
            except Exception:
                continue
    return out


if __name__ == "__main__":
    for s in sys.argv[1:]:
        print(json.dumps({"site": s, "emails": emails_from_site(s)}))
