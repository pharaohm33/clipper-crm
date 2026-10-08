#!/usr/bin/env python3
"""
Finds a podcast's PUBLIC business contact email, from places hosts publish one on purpose:
  1. the podcast's RSS feed (itunes:owner email, the contact address shown to directories)
  2. the YouTube channel description (needs YT_API_KEY)
  3. mailto: links / written addresses on the podcast's own website (home, /contact, /about)
Nothing is guessed (no 'info@' pattern guessing) and nothing is scraped from login-only pages. Every address is checked for
valid syntax and a real mail server (MX record) before it is accepted.

    python3 tools/email_finder.py "The Real Estate InvestHER Show" [https://their-site.com]
"""
import difflib
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (compatible; ClipperCRM contact lookup)"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
JUNK = re.compile(r"(noreply|no-reply|donotreply|do-not-reply|example\.|@sentry|@wixpress|@2x|\.png|\.jpg|\.gif|\.webp|\.svg|u003e|%)", re.I)
_mx_cache = {}


def _get(url, limit=2_000_000, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        chunks, size = [], 0
        while size < limit:  # a single read() can return just the first chunk of a streamed response
            part = r.read(min(65536, limit - size))
            if not part:
                break
            chunks.append(part)
            size += len(part)
    return b"".join(chunks).decode("utf-8", "ignore")


def clean(emails):
    out = []
    for e in emails:
        e = e.strip().strip(".,;:()<>[]\"'").lower()
        if EMAIL_RE.fullmatch(e) and not JUNK.search(e) and e not in out:
            out.append(e)
    return out


def has_mail_server(email):
    """True if the address's domain can receive mail (an MX record, or at least an A record). Unknown = True."""
    domain = email.split("@", 1)[1]
    if domain in _mx_cache:
        return _mx_cache[domain]
    ok = True
    try:
        out = subprocess.run(["nslookup", "-type=mx", domain], capture_output=True, text=True, timeout=12).stdout.lower()
        if "mail exchanger" in out:
            ok = True
        elif "nxdomain" in out or "can't find" in out or "non-existent" in out:
            ok = False
        else:
            a = subprocess.run(["nslookup", domain], capture_output=True, text=True, timeout=12).stdout.lower()
            ok = "address" in a.split("non-authoritative", 1)[-1] and "nxdomain" not in a
    except Exception:
        ok = True
    _mx_cache[domain] = ok
    return ok


def from_text(text):
    return clean(EMAIL_RE.findall(text or ""))


def from_rss(name):
    """(emails, feed_url, matched_title) from the podcast's public feed, found through the free Apple directory search."""
    q = urllib.parse.urlencode({"media": "podcast", "term": name, "limit": 6})
    try:
        hits = json.loads(_get("https://itunes.apple.com/search?" + q, 400_000)).get("results", [])
    except Exception:
        return [], "", ""
    norm = lambda t: re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()
    best, score = None, 0.0
    for h in hits:
        sc = difflib.SequenceMatcher(None, norm(name), norm(h.get("collectionName"))).ratio()
        if sc > score and h.get("feedUrl"):
            best, score = h, sc
    if not best or score < 0.62:
        return [], "", ""
    try:
        text = _get(best["feedUrl"], 400_000)
    except Exception:
        return [], best["feedUrl"], best.get("collectionName", "")
    head = text.split("<item", 1)[0]  # the channel's own details come before the first episode
    found = []
    for pattern in (r"<itunes:owner>.*?<itunes:email>(.*?)</itunes:email>", r"<itunes:email>(.*?)</itunes:email>",
                    r"<managingEditor>(.*?)</managingEditor>", r"<webMaster>(.*?)</webMaster>"):
        for m in re.findall(pattern, head, re.S | re.I):
            found += from_text(re.sub(r"<!\[CDATA\[|\]\]>", "", m))
    return clean(found), best["feedUrl"], best.get("collectionName", "")


def from_youtube(channel_url):
    key = os.getenv("YT_API_KEY")
    m = re.search(r"/channel/(UC[\w-]{20,})", channel_url or "")
    if not (key and m):
        return []
    try:
        j = json.loads(_get("https://www.googleapis.com/youtube/v3/channels?" + urllib.parse.urlencode(
            {"part": "snippet", "id": m.group(1), "key": key}), 200_000))
        return from_text(j["items"][0]["snippet"].get("description", ""))
    except Exception:
        return []


def from_website(site):
    if not site or not site.startswith("http"):
        return []
    base = site.rstrip("/")
    host = urllib.parse.urlparse(base).netloc.lower().replace("www.", "")
    found = []
    for path in ("", "/contact", "/contact-us", "/about"):
        try:
            html = _get(base + path, 600_000, 10)
        except Exception:
            continue
        found += [urllib.parse.unquote(x) for x in re.findall(r"mailto:([^\"'?>\s]+)", html, re.I)] + from_text(html)
    found = clean(found)
    found.sort(key=lambda e: 0 if e.split("@")[1].replace("www.", "") == host else 1)  # their own domain first
    return found


def find_email(name, channel_url="", website="", episode_url="", log=print):
    """Best public contact email for a podcast: {'email','source','others':[...]} or {'email':'', 'tried':[...]}.
    The quick lookups run first. Only a lead that already has an episode found through the YouTube API (so it passed the
    filters) gets the slower browser search: its About page, its website, and the episode page."""
    tried = []
    for source, getter in (("podcast RSS feed", lambda: from_rss(name)[0]),
                           ("YouTube channel description", lambda: from_youtube(channel_url)),
                           ("their website", lambda: from_website(website))):
        try:
            emails = [e for e in getter() if has_mail_server(e)]
        except Exception:
            emails = []
        tried.append(source)
        if emails:
            return {"email": emails[0], "source": source, "others": emails[1:4]}
    if episode_url and os.getenv("EMAIL_BROWSER", "1") != "0":
        tried.append("browser: About page, website, episode page")
        try:
            import email_browser
            log("   opening their pages in Chrome ...")
            got = email_browser.find_in_browser(channel_url, website, episode_url, log=log)
            emails = [e for e in ([got.get("email")] + got.get("others", [])) if e and has_mail_server(e)]
            if emails:
                return {"email": emails[0], "source": got["source"], "others": emails[1:4]}
        except Exception as e:
            log(f"   (browser search failed: {str(e)[:80]})")
    return {"email": "", "tried": tried}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    print(json.dumps(find_email(sys.argv[1], "", sys.argv[2] if len(sys.argv) > 2 else ""), indent=1))
