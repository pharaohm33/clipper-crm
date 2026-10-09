#!/usr/bin/env python3
"""
Public phone numbers for a lead, from places a visitor can already see:

    python3 tools/phone_finder.py "<youtube channel url>" ["<website>"] ["<episode url>"]

Order (stops at the first stage that finds a believable number):
  1. their website, fetched quickly without a browser: tel: links, structured data ("telephone"), and numbers written next to words like call, text, phone, office
  2. a real Chrome visit (only if step 1 found nothing): the YouTube About page, the website's contact style pages, then the episode description

A number is kept only when it looks like a real US/Canada number (area code and exchange start with 2 to 9, not a 555 style placeholder, not repeated digits)
AND it came from a tel: link, structured data, or text next to a phone word. A bare number in the middle of a paragraph is ignored: it is usually an ID or a date.
Toll free numbers (800, 888, ...) are kept but marked, because they usually reach a company line, not a person.
"""
import json
import re
import sys
import urllib.parse
import urllib.request

TOLL_FREE = {"800", "833", "844", "855", "866", "877", "888"}
CONTEXT = re.compile(r"call|text|phone|tel\b|telephone|contact|office|mobile|cell|reach|dial|hotline|\bp:|\bt:|\bm:|\bph\b", re.I)
PHONE_RE = re.compile(r"(?<![\d$])(?:\+?1[\s.\-]?)?\(?([2-9]\d{2})\)?[\s.\-]?([2-9]\d{2})[\s.\-]?(\d{4})(?!\d)")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}


def plausible(area, ex, line):
    digits = area + ex + line
    if len(set(digits)) <= 2:                      # 1111111111, 2222222222
        return False
    if ex == "555" and line.startswith("01"):      # fiction numbers
        return False
    if digits in ("1234567890", "2345678901", "9876543210"):
        return False
    if area[1:] == "11":                           # N11 service codes are not area codes
        return False
    return True


def pretty(area, ex, line):
    return f"({area}) {ex}-{line}"


def extract(text, tel_links=(), schema=()):
    """[{'number','digits','kind','how'}] best first. how = tel link | structured data | next to a phone word."""
    found, seen = [], set()

    def add(m, how, rank):
        area, ex, line = m.group(1), m.group(2), m.group(3)
        if not plausible(area, ex, line):
            return
        digits = area + ex + line
        if digits in seen:
            return
        seen.add(digits)
        found.append({"number": pretty(area, ex, line), "digits": digits, "kind": "toll free" if area in TOLL_FREE else "direct or main line",
                      "how": how, "rank": rank})

    for t in tel_links:
        m = PHONE_RE.search(urllib.parse.unquote(str(t)).replace("tel:", ""))
        if m:
            add(m, "tel link", 0)
    for t in schema:
        m = PHONE_RE.search(str(t))
        if m:
            add(m, "structured data", 1)
    text = str(text or "")
    for m in PHONE_RE.finditer(text):
        if not re.search(r"[\s.\-()]", m.group(0).lstrip("+")):  # a bare run of 10 digits is almost always an ID, an order or a date
            continue
        before = text[max(0, m.start() - 28): m.start()]
        if re.search(r"(#|\border\b|\bid\b|\bref\b|\binvoice\b|\btracking\b|\bticket\b|\bserial\b|\bsku\b|\bno\.)\s*$", before, re.I):
            continue
        around = text[max(0, m.start() - 28): m.end() + 12]
        if CONTEXT.search(around):
            add(m, "next to a phone word", 2)
    found.sort(key=lambda x: (x["rank"], x["kind"] == "toll free"))
    return found


def _http(url, limit=700_000, timeout=10):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit).decode("utf-8", "ignore")


def _from_html(html):
    tel = re.findall(r"href=[\"']tel:([^\"']+)", html, re.I)
    schema = re.findall(r"\"telephone\"\s*:\s*\"([^\"]+)\"", html, re.I)
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return extract(text, tel, schema)


def from_website(site):
    """Quick, no browser. Their home page and the usual contact pages."""
    if not site or not site.startswith("http"):
        return []
    base = site.rstrip("/")
    out = []
    for path in ("", "/contact", "/contact-us", "/about", "/about-us"):
        try:
            out += _from_html(_http(base + path))
        except Exception:
            continue
        if out and path:
            break
    seen, uniq = set(), []
    for x in sorted(out, key=lambda x: (x["rank"], x["kind"] == "toll free")):
        if x["digits"] not in seen:
            seen.add(x["digits"])
            uniq.append(x)
    return uniq


def from_browser(channel_url="", website="", episode_url="", log=print, max_site_pages=4):
    """A real Chrome visit: YouTube About page, website pages, episode description."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []
    import email_browser as B
    out = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception:
                return []
        try:
            page = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-US").new_page()

            def read():
                try:
                    text = page.evaluate("document.body ? document.body.innerText : ''") or ""
                    tel = page.evaluate("[...document.querySelectorAll('a[href^=\"tel:\"]')].map(a => a.getAttribute('href'))") or []
                    html = page.content()
                except Exception:
                    return []
                return extract(text, tel, re.findall(r"\"telephone\"\s*:\s*\"([^\"]+)\"", html, re.I))

            if channel_url and "youtube.com" in channel_url:
                about = channel_url.rstrip("/")
                about = about if about.endswith("/about") else about + "/about"
                if B._goto(page, about, 3):
                    out += read()
                    if not website:
                        try:
                            for h in page.evaluate("[...document.querySelectorAll('a[href]')].map(a => a.href)"):
                                u = B.real_url(h)
                                if u.startswith("http") and not any(s in u.lower() for s in B.SOCIAL):
                                    website = u
                                    break
                        except Exception:
                            pass
            if not out and website:
                site = website if website.startswith("http") else "https://" + website
                visited, queue = set(), [site]
                while queue and len(visited) < max_site_pages and not out:
                    url = queue.pop(0)
                    if url in visited or not B._goto(page, url, 1.6):
                        visited.add(url)
                        continue
                    visited.add(url)
                    out += read()
                    if len(visited) == 1 and not out:
                        try:
                            links = page.evaluate("[...document.querySelectorAll('a[href]')].map(a => [a.href, (a.innerText || '').trim()])")
                        except Exception:
                            links = []
                        for href, label in links:
                            u = urllib.parse.urljoin(url, href).split("#")[0]
                            if (B._domain(u) == B._domain(url)) and B.PAGE_HINT.search(label + " " + urllib.parse.urlparse(u).path) and u not in visited and u not in queue:
                                queue.append(u)
            if not out and episode_url and "youtube.com" in episode_url and B._goto(page, episode_url, 3):
                try:
                    desc = page.evaluate("['#description-inner', '#description-inline-expander', 'ytd-watch-metadata #description'].map(s => (document.querySelector(s) || {}).textContent || '').join(' ')")
                except Exception:
                    desc = ""
                out += extract(desc)
        finally:
            browser.close()
    return out


def find_phone(name="", channel_url="", website="", episode_url="", log=print):
    """{'phone','others','how','source','kind'} or {'phone': ''}. Fast website check first, Chrome only if that finds nothing."""
    for source, getter in (("their website", lambda: from_website(website)),
                           ("browser: About page, website, episode page", lambda: from_browser(channel_url, website, episode_url, log))):
        try:
            hits = getter()
        except Exception as e:
            log(f"   (phone search failed: {str(e)[:80]})")
            hits = []
        if hits:
            best = hits[0]
            return {"phone": best["number"], "others": [h["number"] for h in hits[1:4]], "how": best["how"], "kind": best["kind"], "source": source}
    return {"phone": ""}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    a = sys.argv[1:]
    print(json.dumps(find_phone("", a[0], a[1] if len(a) > 1 else "", a[2] if len(a) > 2 else ""), indent=1))
