#!/usr/bin/env python3
"""
Google AI Mode -> Clipper CRM

Opens Google AI Mode in YOUR Chrome (separate profile, so you log in once), asks it for podcasts per
niche, reads the answer table (including the hidden links), and appends new leads to your CRM Sheet.
The website merges them in the next time you open it.

Setup (once):
  pip install playwright requests
  export CRM_SYNC_URL="https://script.google.com/macros/s/.../exec"   # your Apps Script web app URL
  export CRM_SYNC_PASSWORD="..."                                      # the sync password you set
  export YT_API_KEY="..."        # optional: adds subscriber counts + exact channel ids, filters by size

Run:
  python tools/google_ai_to_crm.py "real estate" "personal finance"
  python tools/google_ai_to_crm.py --count 10 --dry-run "fitness"
No Google login needed (Google blocks sign-in in automated browsers). Runs signed out.
"""
import argparse, difflib, json, os, random, re, sys, time
from datetime import date
from pathlib import Path
from urllib.parse import quote

import requests

PROFILE = Path.home() / ".clipper_chrome_profile"
RUNS = Path(__file__).resolve().parent / "runs"

EXTRACT_JS = """() => {
  const out = {tables: [], text: document.body.innerText, tables_n: document.querySelectorAll('table').length};
  document.querySelectorAll('table').forEach(t => {
    out.tables.push([...t.querySelectorAll('tr')].map(tr => [...tr.querySelectorAll('th,td')].map(c => ({
      t: c.innerText.trim(), h: [...c.querySelectorAll('a[href]')].map(a => a.href)}))));
  });
  return out;
}"""


def load_env():
    f = Path(__file__).resolve().parent / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def build_prompt(niche, count, focus=""):
    return (f"List {count} {niche} podcasts or YouTube shows{' ' + focus if focus else ''} that: post full length episodes (20 minutes or longer) at least every two weeks and posted in the last 30 days; "
            "post few or no YouTube Shorts; and where the host runs a real business behind the show, selling a product or service that costs $1,000 or more (for example a coaching program, agency, "
            "brokerage, builder, practice, dealership or course) or has sponsors. Prefer owner led channels, including newer channels under a year old, and skip big networks and media companies. "
            "For each one give the show name, the YouTube channel link, a recent full length episode title with its direct YouTube watch link, the host's Instagram handle, and their website. Format it as a table.")


def _pause(a=0.8, b=2.2):
    time.sleep(random.uniform(a, b))


def open_ai_mode(page, prompt):
    """Gets to AI Mode the way a person does: open google.com, press the AI Mode button, type the question, press Enter.
    Jumping straight to the AI Mode address with the question in it is what tends to trigger the 'are you a robot' page.
    Returns True when the question was submitted this way, False when it fell back to the direct address."""
    try:
        page.goto("https://www.google.com/", wait_until="domcontentloaded")
        _pause(1.5, 3)
        for label in ("Reject all", "Accept all", "I agree"):  # cookie box in some regions: pick the least tracking option first
            b = page.get_by_role("button", name=label)
            if b.count():
                b.first.click()
                _pause()
                break
        btn = page.get_by_role("button", name=re.compile(r"^AI Mode$", re.I))
        if not btn.count():
            btn = page.get_by_role("link", name=re.compile(r"^AI Mode$", re.I))
        if not btn.count():
            btn = page.locator("a[href*='udm=50'], [aria-label*='AI Mode' i]")
        if not btn.count():
            raise RuntimeError("no AI Mode button on the page")
        btn.first.click()
        _pause(1.5, 3)
        box = page.locator("textarea:visible, input[type=text]:visible, [contenteditable=true]:visible").first
        box.click()
        _pause(0.4, 1.0)
        page.keyboard.type(prompt, delay=random.randint(6, 18))
        _pause(0.6, 1.4)
        page.keyboard.press("Enter")
        return True
    except Exception as e:
        print(f"  (could not use the AI Mode button: {str(e)[:80]}; opening it directly)")
        page.goto("https://www.google.com/search?udm=50&q=" + quote(prompt), wait_until="domcontentloaded")
        return False


def ask_google_ai(page, prompt, timeout=120):
    open_ai_mode(page, prompt)
    start, last_text, stable_since = time.time(), "", time.time()
    while time.time() - start < timeout:
        time.sleep(2)
        body = page.inner_text("body")
        if re.search(r"unusual traffic|not a robot|captcha", body, re.I):
            print("  Google is asking you to verify. Solve it in the Chrome window; waiting up to 5 minutes...")
            for _ in range(150):
                time.sleep(2)
                if not re.search(r"unusual traffic|not a robot|captcha", page.inner_text("body"), re.I):
                    break
            return ask_google_ai(page, prompt, timeout)
        if "no response available" in body:
            return None
        if page.locator("table").count() > 0 and time.time() - start > 8:
            time.sleep(3)  # let the table finish streaming
            return page.evaluate(EXTRACT_JS)
        if body != last_text:
            last_text, stable_since = body, time.time()
        elif time.time() - stable_since > 12 and time.time() - start > 20:
            return page.evaluate(EXTRACT_JS)  # answer stopped changing, probably no table
    return page.evaluate(EXTRACT_JS)


_resolved = {}


def unwrap(h):
    """Signed-out Google AI wraps links as google.com/goto?url=...; one HTTP hop reveals the real URL."""
    if "google.com/goto" not in h and "google.com/url" not in h:
        return h
    if h in _resolved:
        return _resolved[h]
    real = h
    try:
        for _ in range(3):
            r = requests.get(real, allow_redirects=False, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            loc = r.headers.get("Location", "")
            if r.status_code in (301, 302, 303, 307, 308) and loc:
                real = loc if loc.startswith("http") else real
                if "google.com/goto" not in real and "google.com/url" not in real:
                    break
            else:
                break
    except Exception:
        pass
    _resolved[h] = real
    return real


def clean_handle(s):
    s = (s or "").strip().lstrip("@")
    s = re.sub(r"[^A-Za-z0-9._]", "", s)
    return "" if s.lower() in ("", "unknown", "na", "none", "no") else s


def parse_tables(data):
    items = []
    for rows in data.get("tables", []):
        if len(rows) < 2:
            continue
        head = [c["t"].lower() for c in rows[0]]
        def col(rx, bad=None):
            for i, h in enumerate(head):
                if re.search(rx, h) and not (bad and re.search(bad, h)):
                    return i
            return -1
        ni, ci, ei, ii = col(r"podcast|show|name", r"episode"), col(r"channel"), col(r"episode|title"), col(r"instagram|\big\b")
        xi, ti = col(r"\bx\b|twitter"), col(r"tiktok")
        rows = [rows[0]] + [[{"t": c["t"], "h": [unwrap(h) for h in c["h"]]} for c in r] for r in rows[1:]]
        for r in rows[1:]:
            get = lambda i: r[i] if 0 <= i < len(r) else {"t": "", "h": []}
            it = {"name": get(ni if ni >= 0 else 0)["t"], "channel": "", "episode_url": "", "episode_title": "",
                  "ig": "", "x": "", "tt": ""}
            for h in get(ci)["h"] + [h for c in r for h in c["h"]]:
                if re.search(r"youtube\.com/(@|channel/|c/|user/)", h) and not it["channel"]:
                    it["channel"] = h.split("?")[0]
            for h in get(ei)["h"] + [h for c in r for h in c["h"]]:
                if re.search(r"youtube\.com/watch\?v=|youtu\.be/", h):
                    it["episode_url"] = h
                    break
            it["episode_title"] = get(ei)["t"] if not get(ei)["t"].startswith("http") else ""
            ig = get(ii)
            m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", " ".join(ig["h"] + [h for c in r for h in c["h"]]))
            it["ig"] = clean_handle(ig["t"]) or (clean_handle(m.group(1)) if m else "")
            if it["ig"] in ("p", "reel", "explore"):
                it["ig"] = ""
            xh = clean_handle(get(xi)["t"])
            it["x"] = f"https://x.com/{xh}" if xh else ""
            th = clean_handle(get(ti)["t"])
            it["tt"] = f"https://tiktok.com/@{th}" if th else ""
            if it["name"] and (it["channel"] or it["episode_url"] or it["ig"]):
                items.append(it)
    return items


class YT:
    def __init__(self, key):
        self.key = key

    def get(self, path, **p):
        r = requests.get("https://www.googleapis.com/youtube/v3/" + path, params={**p, "key": self.key}, timeout=30)
        j = r.json()
        if "error" in j:
            raise RuntimeError(j["error"].get("message", "YouTube API error"))
        return j

    def channel(self, url, video_id=""):
        if video_id:
            v = self.get("videos", part="snippet", id=video_id)
            if v.get("items"):
                return self.get("channels", part="snippet,statistics,contentDetails", id=v["items"][0]["snippet"]["channelId"])["items"][0]
        m = re.search(r"youtube\.com/channel/(UC[\w-]{20,})", url or "")
        if m:
            return self.get("channels", part="snippet,statistics,contentDetails", id=m.group(1))["items"][0]
        m = re.search(r"youtube\.com/(@[\w.-]+)", url or "") or re.search(r"youtube\.com/(?:c|user)/([\w.-]+)", url or "")
        if m:
            j = self.get("channels", part="snippet,statistics,contentDetails", forHandle=m.group(1) if m.group(1).startswith("@") else "@" + m.group(1))
            return j["items"][0] if j.get("items") else None
        return None

    def pick_episode(self, ch, want_title=""):
        """Returns (video_id, title, shorts_pct, sample_size) from the channel's last 30 uploads."""
        pl = self.get("playlistItems", part="contentDetails", playlistId=ch["contentDetails"]["relatedPlaylists"]["uploads"], maxResults=30)
        ids = [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
        if not ids:
            return "", "", None, 0
        vids = self.get("videos", part="contentDetails,snippet", id=",".join(ids))["items"]
        def secs(d):
            m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d)
            return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)
        shorts = sum(1 for v in vids if secs(v["contentDetails"]["duration"]) <= 180
                     or re.search(r"#shorts?\b", v["snippet"]["title"] + " " + (v["snippet"].get("description") or "")[:300], re.I))
        pct = round(100 * shorts / len(vids)) if vids else None
        longs = [v for v in vids if 1200 <= secs(v["contentDetails"]["duration"]) <= 14400] or vids
        if want_title:
            best = max(longs, key=lambda v: difflib.SequenceMatcher(None, want_title.lower(), v["snippet"]["title"].lower()).ratio())
            if difflib.SequenceMatcher(None, want_title.lower(), best["snippet"]["title"].lower()).ratio() > 0.6:
                return best["id"], best["snippet"]["title"], pct, len(vids)
        return longs[0]["id"], longs[0]["snippet"]["title"], pct, len(vids)

def to_leads(items, niche, yt, max_shorts=100):
    leads, too_shorty = [], 0
    for it in items:
        vid = (re.search(r"(?:v=|youtu\.be/)([\w-]{11})", it["episode_url"]) or [None, ""])[1]
        lead = {"id": "", "name": it["name"], "niche": niche, "url": it["channel"], "subs": 0, "last": "",
                "episode": it["episode_url"], "epTitle": it["episode_title"], "shortsPct": None,
                "ig": f"https://instagram.com/{it['ig']}" if it["ig"] else "",
                "x": it["x"], "tt": it["tt"], "web": "", "status": "New", "added": date.today().isoformat(),
                "sent": "", "follow": "", "notes": "From Google AI, verify Instagram"}
        skip = False
        if yt:
            try:
                ch = yt.channel(it["channel"], vid)
                if not ch:
                    sr = yt.get("search", part="snippet", type="channel", q=it["name"] + " podcast", maxResults=1)
                    if sr.get("items"):
                        ch = yt.get("channels", part="snippet,statistics,contentDetails", id=sr["items"][0]["snippet"]["channelId"])["items"][0]
                if ch:
                    lead.update(id=ch["id"], name=ch["snippet"]["title"], url="https://www.youtube.com/channel/" + ch["id"],
                                subs=int(ch["statistics"].get("subscriberCount", 0) or 0))
                    v, t, pct, total = yt.pick_episode(ch, it["episode_title"])
                    lead["shortsPct"] = pct
                    if pct is not None and total >= 5 and pct > max_shorts:
                        skip = True
                    if v and not lead["episode"]:
                        lead["episode"], lead["epTitle"] = "https://www.youtube.com/watch?v=" + v, t
            except Exception as e:
                print(f"  YouTube lookup failed for {it['name']}: {e}")
        if skip:
            too_shorty += 1
            continue
        if not lead["id"]:
            lead["id"] = "m:" + (it["ig"] or it["channel"] or it["name"]).lower()
        if lead["episode"] or lead["ig"]:
            leads.append(lead)
    if too_shorty:
        print(f"  skipped {too_shorty} with more than {max_shorts}% Shorts")
    return leads

def crm(url, pw, **payload):
    r = requests.post(url, data=json.dumps({"secret": pw, **payload}), headers={"Content-Type": "text/plain"}, timeout=60)
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(j.get("error", "CRM error"))
    return j


def main():
    ap = argparse.ArgumentParser(description="Google AI Mode -> Clipper CRM")
    ap.add_argument("niches", nargs="*")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--focus", default="", help='comma separated angles to vary results, e.g. "in Texas,in Florida,for first time buyers"')
    ap.add_argument("--dry-run", action="store_true", help="parse and print, don't send to the CRM")
    ap.add_argument("--emit", action="store_true", help="print the parsed shows as AIITEMS lines for the website to filter with its own quality checks (no Sheet, no YouTube key needed here)")
    ap.add_argument("--max-shorts", type=int, default=20, help="skip channels whose recent uploads are more than this %% Shorts (needs YT_API_KEY)")
    ap.add_argument("--min-subs", type=int, default=1000)
    ap.add_argument("--max-subs", type=int, default=150000)
    a = ap.parse_args()
    load_env()

    from playwright.sync_api import sync_playwright
    url, pw, key = os.getenv("CRM_SYNC_URL"), os.getenv("CRM_SYNC_PASSWORD"), os.getenv("YT_API_KEY")
    if not (a.dry_run or a.emit) and not (url and pw):
        sys.exit("Set CRM_SYNC_URL and CRM_SYNC_PASSWORD (or use --dry-run).")
    if not a.niches:
        sys.exit("Give at least one niche, e.g.  python tools/google_ai_to_crm.py \"real estate\"")
    yt = YT(key) if key else None
    RUNS.mkdir(exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), channel="chrome", headless=False, viewport={"width": 1200, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        existing = set()
        if url and pw and not a.dry_run and not a.emit:
            for l in crm(url, pw, action="pull")["state"].get("leads", []):
                existing.add(l["id"])
                existing.add("n:" + str(l.get("name", "")).strip().lower())
                if l.get("ig"):
                    existing.add("ig:" + l["ig"].rstrip("/").split("/")[-1].lower())
        total = 0
        jobs = [(n_, f_) for n_ in a.niches for f_ in ([x.strip() for x in a.focus.split(",") if x.strip()] or [""])]
        for n, (niche, focus) in enumerate(jobs):
            print(f"[{niche} {focus}] asking Google AI...".replace(" ]", "]"))
            data = ask_google_ai(page, build_prompt(niche, a.count, focus))
            if not data:
                print("  no response from Google AI for this prompt; skipping")
                continue
            (RUNS / f"{date.today()}_{re.sub(r'[^a-z0-9]+', '_', (niche + ' ' + focus).lower())}.json").write_text(json.dumps(data, indent=1))
            items = parse_tables(data)
            if not items:
                print("  no table found. Raw answer saved in tools/runs/ (paste it into the website's Paste box).")
                continue
            if a.emit:
                mapped = [{"name": it.get("name", ""), "youtube_url": it.get("channel", ""), "episode_url": it.get("episode_url", ""), "episode_title": it.get("episode_title", ""),
                           "instagram_handle": it.get("ig", ""), "x_url": it.get("x", ""), "tiktok_url": it.get("tt", "")} for it in items]
                print("AIITEMS " + json.dumps({"niche": niche, "items": mapped}))
                print(f"  parsed {len(items)} shows for the website to check")
                total += len(items)
                if n < len(jobs) - 1:
                    time.sleep(random.uniform(20, 40))
                continue
            leads = to_leads(items, niche, yt, a.max_shorts)
            fresh = []
            for l in leads:
                igk = "ig:" + l["ig"].rstrip("/").split("/")[-1].lower() if l["ig"] else ""
                if l["id"] in existing or ("n:" + l["name"].strip().lower()) in existing or (igk and igk in existing):
                    continue
                if l["subs"] and not (a.min_subs <= l["subs"] <= a.max_subs):
                    continue
                existing.add(l["id"])
                existing.add("n:" + l["name"].strip().lower())
                if igk:
                    existing.add(igk)
                fresh.append(l)
            print(f"  parsed {len(items)}, new {len(fresh)}")
            for l in fresh:
                print(f"   - {l['name']} | IG {l['ig'] or '-'} | {l['shortsPct'] if l['shortsPct'] is not None else '?'}% Shorts | {l['episode'] or 'no episode'}")
            if fresh and not a.dry_run:
                print(f"  added {crm(url, pw, action='append', leads=fresh).get('added')} to the CRM")
            total += len(fresh)
            if n < len(jobs) - 1:
                time.sleep(random.uniform(20, 40))
        print(f"Done. {total} new leads.")
        ctx.close()


if __name__ == "__main__":
    main()
