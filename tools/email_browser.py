#!/usr/bin/env python3
"""
Last resort email finder: opens pages in a real Chrome (Playwright) and reads only what a visitor can already see.

    python3 tools/email_browser.py "<youtube channel url>" ["<website>"] ["<episode url>"]

Order (stops at the first address that can receive mail):
  1. the channel's About page (description text and links; the website link is picked up from here if you did not give one)
  2. their website: the home page, then up to 3 contact/about/booking style pages (mailto links, plain text, "name [at] site [dot] com",
     Cloudflare protected addresses)
  3. the episode page: the video description, plus the creator's own comments and the pinned comment (never other viewers' comments)

It never solves captchas or signs in. YouTube hides its "business email" behind a captcha button; that is left alone.
Pages are visited slowly and only a handful per lead.
"""
import json
import random
import re
import sys
import time
from urllib.parse import parse_qs, unquote, urljoin, urlparse

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
BAD_DOMAINS = ("sentry", "wixpress", "example.", "domain.", "youtube.", "google.", "gstatic", "schema.org", "w3.org", "yourdomain",
               "email.com", "godaddy", "squarespace", "wordpress", "cloudflare")
BAD_LOCAL = ("noreply", "no-reply", "donotreply", "do-not-reply", "privacy", "abuse", "postmaster", "webmaster", "unsubscribe")
GOOD_LOCAL = ("business", "contact", "hello", "hi", "info", "booking", "bookings", "podcast", "collab", "partnerships", "partner",
              "sponsor", "sponsors", "team", "press", "media", "work", "inquiries", "enquiries", "management")
SOCIAL = ("instagram.", "twitter.", "x.com", "tiktok.", "facebook.", "linkedin.", "spotify.", "apple.", "youtube.", "youtu.be", "patreon.",
          "amazon.", "google.", "discord.", "threads.", "pinterest.", "reddit.")
PAGE_HINT = re.compile(r"contact|about|work.?with|book|press|sponsor|advertis|podcast|team|connect|hire|inquir|collab", re.I)
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")


def deobfuscate(text):
    t = re.sub(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", "@", text, flags=re.I)
    return re.sub(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", ".", t, flags=re.I)


def decode_cfemail(hexstr):
    try:
        b = bytes.fromhex(hexstr)
        return "".join(chr(c ^ b[0]) for c in b[1:])
    except Exception:
        return ""


def clean_emails(text, site_domain=""):
    """Plausible addresses found in text, best first (business style names and the lead's own domain rank higher)."""
    seen, out = set(), []
    for e in EMAIL_RE.findall(deobfuscate(text or "")):
        e = e.strip(".,;:").lower()
        local, _, dom = e.partition("@")
        if e in seen or e.endswith(IMAGE_EXT) or any(b in dom for b in BAD_DOMAINS) or any(b in local for b in BAD_LOCAL):
            continue
        seen.add(e)
        out.append(e)

    def rank(e):
        local, _, dom = e.partition("@")
        return -((2 if site_domain and dom.endswith(site_domain) else 0) + (1 if local in GOOD_LOCAL else 0))
    return sorted(out, key=rank)


def real_url(href):
    """YouTube wraps outside links in youtube.com/redirect?q=<url>."""
    if "youtube.com/redirect" in href:
        q = parse_qs(urlparse(href).query).get("q")
        return unquote(q[0]) if q else ""
    return href


def _domain(url):
    d = urlparse(url if "//" in url else "//" + url).netloc.lower()
    return d[4:] if d.startswith("www.") else d


def _page_emails(page, site_domain=""):
    """Everything a visitor could read on the current page: text, mailto links, protected addresses."""
    try:
        text = page.evaluate("document.body ? document.body.innerText : ''") or ""
        extra = page.evaluate("""() => [...document.querySelectorAll('a[href^="mailto:"]')].map(a => decodeURIComponent(a.getAttribute('href').slice(7).split('?')[0]))
            .concat([...document.querySelectorAll('[data-cfemail]')].map(e => 'CF:' + e.getAttribute('data-cfemail')))""") or []
    except Exception:
        return []
    decoded = [decode_cfemail(x[3:]) if x.startswith("CF:") else x for x in extra]
    return clean_emails(" ".join(decoded) + " " + text, site_domain)


def _goto(page, url, wait=2.2):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        time.sleep(wait + random.random())
        return True
    except Exception:
        return False


def find_in_browser(channel_url="", website="", episode_url="", log=print, max_site_pages=4):
    """{'email','source','others'} or {} (nothing found). Imports Playwright lazily so the rest of the tools work without it."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        log("   (browser search skipped: Playwright is not installed)")
        return {}
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:
                log(f"   (browser search skipped: could not start Chrome: {str(e)[:80]})")
                return {}
        try:
            page = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-US").new_page()
            site_domain = _domain(website) if website else ""

            # 1) YouTube About page
            if channel_url and "youtube.com" in channel_url:
                about = channel_url.rstrip("/")
                about = about if about.endswith("/about") else about + "/about"
                if _goto(page, about, 3):
                    found = _page_emails(page, site_domain)
                    if found:
                        return {"email": found[0], "source": "YouTube About page (browser)", "others": found[1:4]}
                    if not website:
                        try:
                            for h in page.evaluate("[...document.querySelectorAll('a[href]')].map(a => a.href)"):
                                u = real_url(h)
                                if u.startswith("http") and not any(s in u.lower() for s in SOCIAL):
                                    website, site_domain = u, _domain(u)
                                    break
                        except Exception:
                            pass

            # 2) their website
            if website:
                site = website if website.startswith("http") else "https://" + website
                visited, queue = set(), [site]
                while queue and len(visited) < max_site_pages:
                    url = queue.pop(0)
                    if url in visited or not _goto(page, url, 1.6):
                        visited.add(url)
                        continue
                    visited.add(url)
                    found = _page_emails(page, site_domain)
                    if found:
                        return {"email": found[0], "source": "their website (browser)", "others": found[1:4]}
                    if len(visited) == 1:
                        try:
                            links = page.evaluate("[...document.querySelectorAll('a[href]')].map(a => [a.href, (a.innerText || '').trim()])")
                        except Exception:
                            links = []
                        for href, label in links:
                            u = urljoin(url, href).split("#")[0]
                            if (_domain(u) == _domain(url) or _domain(url).endswith(_domain(u))) and PAGE_HINT.search(label + " " + urlparse(u).path) \
                                    and u not in visited and u not in queue:
                                queue.append(u)

            # 3) the episode page: description, and only the creator's own and pinned comments
            if episode_url and "youtube.com" in episode_url:
                if _goto(page, episode_url, 3):
                    texts = []
                    try:
                        texts.append(page.evaluate("['#description-inner', '#description-inline-expander', 'ytd-watch-metadata #description'].map(s => (document.querySelector(s) || {}).textContent || '').join(' ')"))
                    except Exception:
                        pass
                    for _ in range(3):
                        try:
                            page.mouse.wheel(0, 1100)
                        except Exception:
                            break
                        time.sleep(1.4)
                    try:
                        texts += page.evaluate("""() => [...document.querySelectorAll('ytd-comment-thread-renderer')].slice(0, 40)
                            .filter(t => t.querySelector('ytd-pinned-comment-badge-renderer') || t.querySelector('ytd-author-comment-badge-renderer'))
                            .map(t => (t.querySelector('#content-text') || {}).innerText || '')""") or []
                    except Exception:
                        pass
                    found = clean_emails(" ".join(texts), site_domain)
                    if found:
                        return {"email": found[0], "source": "episode description or the creator's comments (browser)", "others": found[1:4]}
            return {}
        finally:
            browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    a = sys.argv[1:]
    print(json.dumps(find_in_browser(a[0], a[1] if len(a) > 1 else "", a[2] if len(a) > 2 else ""), indent=1))
