#!/usr/bin/env python3
"""
A narrated, face-free video of a prospect's own Meta ads, made without anyone recording anything.

    python3 tools/ad_video.py '{"id":"x","company":"Uproot Clean","email":"hi@uprootclean.com","web":"https://uprootclean.com","first":"Sophia","business":"Uproot Clean"}'

For each lead:
  1. Finds the advertiser in the Meta Ad Library by the email's domain (the website's domain if the email is Gmail and the like).
  2. BRAND CHECK: reads the destination domain of the ads on that advertiser's page and only goes on when they really point at the lead's own domain.
     A lookalike advertiser with a similar name is rejected.
  3. Loads the advertiser's own view with the filters cleared (active AND inactive), then the "active" view, and reads the real counts.
     No active ads means no video: there is nothing true to show.
  4. Writes a short script from those facts only (active count, how many ads share one creative, the offer), speaks it with a free voice, and records
     the page scrolling. Output: tools/ad_videos/<id>.mp4 and <id>.json with the facts behind every number said.

The script never claims anything it did not read off the page, and it says "I took a look at", never "I'm looking right now".
"""
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "ad_videos"
FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com", "live.com", "msn.com", "me.com", "protonmail.com", "ymail.com",
             "comcast.net", "att.net", "sbcglobal.net", "verizon.net", "bellsouth.net", "googlemail.com"}
LIB = "https://www.facebook.com/ads/library/"
VIEWPORT = {"width": 1280, "height": 720}
DEFAULT_VOICE = "en-US-AndrewNeural"
SIGNUP_LINK = "https://portal.aiadsoptimization.com/signup"
LINK_SECONDS = 20  # the sign up link stays on screen for at least the last 20 seconds


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def brand_domain(email, web):
    """The domain whose ads we expect to see: the email's, or the website's when the email is a free mailbox."""
    d = str(email or "").split("@")[-1].lower().strip()
    if d and d not in FREE_MAIL:
        return d
    w = re.sub(r"^https?://(www\.)?", "", str(web or "").lower()).split("/")[0]
    return w


def root_label(domain):
    parts = [p for p in str(domain).lower().split(".") if p and p != "www"]
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov") and len(parts[-1]) == 2:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")


def host_matches(host, label):
    """order.uprootclean.com, www.uprootclean.co and uprootclean.com all match the label 'uprootclean'."""
    label = norm(label)
    if len(label) < 4:
        return False
    return any(norm(part) == label or (len(label) >= 6 and norm(part).startswith(label)) for part in str(host).lower().split("."))


def name_close(a, b):
    import difflib
    a, b = norm(a), norm(b)
    return bool(a and b) and (a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8)


def lib_url(**kw):
    q = {"active_status": "all", "ad_type": "all", "country": "US", "media_type": "all"}
    q.update(kw)
    return LIB + "?" + urllib.parse.urlencode(q)


def settle(pg, log, secs=11):
    """Waits for results or the 'no ads' message. Returns 'results', 'none' or 'timeout'."""
    for _ in range(int(secs * 2)):
        pg.wait_for_timeout(500)
        t = pg.inner_text("body")
        if re.search(r"~?[\d,]+ results?", t):
            return "results"
        if "No ads match" in t:
            return "none"
    return "timeout"


def clear_filters(pg, log):
    """The Ad Library sometimes opens with a filter on (for example Active ads only). Open Filters, Clear all, Apply."""
    try:
        pg.get_by_role("button", name=re.compile(r"^Filters", re.I)).first.click(timeout=4000)
        pg.wait_for_timeout(1200)
        pg.get_by_text(re.compile(r"^Clear all$", re.I)).first.click(timeout=4000)
        pg.wait_for_timeout(500)
        ap = pg.get_by_role("button", name=re.compile(r"^Apply", re.I)).first
        ap.click(timeout=4000)
        pg.wait_for_timeout(2500)
        log("  cleared the filters")
        return True
    except Exception:
        try:
            pg.keyboard.press("Escape")
        except Exception:
            pass
        return False


def count_results(pg):
    t = pg.inner_text("body")
    m = re.search(r"~?([\d,]+) results?", t)
    return int(m.group(1).replace(",", "")) if m else 0


def dest_hosts(pg):
    return pg.evaluate("""()=>[...document.querySelectorAll("a[href*='l.facebook.com/l.php']")].map(a=>{try{return new URL(new URL(a.href).searchParams.get('u')).hostname.toLowerCase()}catch(e){return ''}}).filter(Boolean)""")


def candidates(pg, domain, company, log):
    """Advertiser ids from a keyword search on the domain (then on the company name), most frequent first: [(page_id, page_name)]."""
    out = []
    for q in (domain, company):
        if not q:
            continue
        pg.goto(lib_url(q=q, search_type="keyword_unordered"), wait_until="domcontentloaded")
        state = settle(pg, log)
        if state != "results":
            continue
        for _ in range(2):
            pg.mouse.wheel(0, 900)
            pg.wait_for_timeout(1200)
        html = pg.content()
        pairs = re.findall(r'"page_id":"(\d+)"[^{}]{0,300}?"page_name":"([^"]+)"', html) + [(i, n) for n, i in re.findall(r'"page_name":"([^"]+)"[^{}]{0,300}?"page_id":"(\d+)"', html)]
        freq = {}
        for i, n in pairs:
            freq.setdefault((i, n), 0)
            freq[(i, n)] += 1
        for (i, n), _c in sorted(freq.items(), key=lambda kv: -kv[1]):
            if (i, n) not in out:
                out.append((i, n))
        if out:
            break
    return out[:4]


def read_cards(pg):
    """[{status, started, shared}] for the ads loaded so far, from the page text."""
    for _ in range(4):
        pg.mouse.wheel(0, 1100)
        pg.wait_for_timeout(1300)
    t = pg.inner_text("body").replace("​", "")
    parts = re.split(r"\n(?=(?:Active|Inactive)\s*\n\s*Library ID:)", t)
    cards = []
    for seg in parts[1:]:
        st = re.match(r"(Active|Inactive)", seg)
        if not st:
            continue
        sh = re.search(r"(\d+) ads use this creative and text", seg[:700])
        sd = re.search(r"Started running on ([A-Za-z]+ \d+, \d{4})", seg[:300])
        cards.append({"status": st.group(1), "started": sd.group(1) if sd else "", "shared": int(sh.group(1)) if sh else 0})
    return cards


def view_url(pid, status):
    return lib_url(active_status=status, view_all_page_id=pid, search_type="page")


def inspect(pg, pid, label, log):
    """Loads the advertiser's own view (filters cleared) and returns the facts, or None when the page does not belong to this brand."""
    pg.goto(view_url(pid, "all"), wait_until="domcontentloaded")
    state = settle(pg, log)
    if state != "results":
        if clear_filters(pg, log):
            state = settle(pg, log)
    if state != "results":
        return {"page_id": pid, "ok": False, "reason": "the advertiser page shows no ads even with the filters cleared"}
    total = count_results(pg)
    for _ in range(3):
        pg.mouse.wheel(0, 900)
        pg.wait_for_timeout(1200)
    hosts = dest_hosts(pg)
    match = [h for h in hosts if host_matches(h, label)]
    rate = len(match) / len(hosts) if hosts else 0.0
    # active view: how many are running right now
    pg.goto(view_url(pid, "active"), wait_until="domcontentloaded")
    st = settle(pg, log)
    if st == "none":
        active = 0
    elif st == "results":
        active = count_results(pg)
    else:
        if clear_filters(pg, log):
            pg.goto(view_url(pid, "active"), wait_until="domcontentloaded")
            st = settle(pg, log)
        active = count_results(pg) if st == "results" else 0
    cards = read_cards(pg) if active else []
    shared_cards = [c for c in cards if c["shared"] >= 2]
    looked = len(cards)
    return {"page_id": pid, "ok": True, "total": total, "active": active, "hosts": sorted(set(hosts))[:8], "host_match_rate": round(rate, 2),
            "matching_hosts": sorted(set(match))[:6], "looked": looked, "shared_creative_ads": len(shared_cards), "max_shared": max([c["shared"] for c in shared_cards] or [0]),
            "oldest_active_start": (sorted([c["started"] for c in cards if c["started"]])[:1] or [""])[0]}


def say(n):
    return f"{n:,}"


def build_script(facts, first, business, sender, product, price="20 percent", host="loom"):
    """Only what was read off the page."""
    a, t, sc = facts["active"], facts["total"], facts["shared_creative_ads"]
    poss = business + ("'" if business.lower().endswith("s") else "'s")
    lines = [f"Hey {first}, it's {sender}.", f"I took a look at {poss} ads in the Meta Ad Library."]
    lines.append(f"I can see {say(a)} active ad{'s' if a != 1 else ''} right now" + (f", out of about {say(t)} in the library." if t > a else "."))
    if sc >= 2 and facts.get("looked", 0) >= sc:
        lines.append(f"{sc} of the first {facts['looked']} ads I looked at share the same creative and text, which is often worth checking for overlap and wasted spend.")
    lines.append(f"{product} connects to your Meta ads account, monitors your campaigns around the clock, and automatically cuts wasted ad spend.")
    lines.append(f"There's no setup fee, and we only take {price} of the money we actually save you. If we don't save you anything, you don't pay anything.")
    if host == "loom":  # on Loom the link is clickable in the comments and the link area under the video
        lines.append("If that sounds worth a look, you can visit our website with the link in the comments and the link area under this video. It's on your screen now too, and in my email, or just reply to my email.")
    else:
        lines.append("If that sounds worth a look, the sign up link is on your screen now and in my email, or just reply to my email.")
    return " ".join(lines)


def _t(s):
    h, m, rest = s.split(":")
    sec, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def speak(text, voice, mp3, log):
    """Speaks the script. Returns (seconds, [(start, end, sentence), ...]) so the sign up link can appear when the call to action is spoken."""
    vtt = Path(str(mp3) + ".vtt")
    r = subprocess.run([sys.executable, "-m", "edge_tts", "--voice", voice, "--text", text, "--write-media", str(mp3), "--write-subtitles", str(vtt)], capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not Path(mp3).exists() or Path(mp3).stat().st_size < 2000:
        raise RuntimeError("the free voice service did not answer: " + (r.stderr or "")[-160:])
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)], capture_output=True, text=True)
    cues = []
    try:
        for blk in vtt.read_text(encoding="utf-8").split("\n\n"):
            m = re.search(r"(\d\d:\d\d:\d\d,\d+) --> (\d\d:\d\d:\d\d,\d+)\s*\n(.+)", blk.strip(), re.S)
            if m:
                cues.append((_t(m.group(1)), _t(m.group(2)), m.group(3).strip()))
        vtt.unlink()
    except Exception:
        pass
    return float(d.stdout.strip() or 0), cues


def link_start(cues, seconds):
    """When the sign up link goes on screen: where the call to action is spoken, but never later than LINK_SECONDS before the end."""
    cta = next((s for s, _e, t in cues if re.search(r"sign up link|worth a look", t, re.I)), None)
    late = max(0.0, seconds - LINK_SECONDS)
    return min(cta, late) if cta is not None else late


STRIP_JS = r"""()=>{
 const URLRX=/(https?:\/\/\S+|www\.\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|co|io|shop|store|us|ca|uk|au|ai|app|info|biz|tv|me|xyz|online|site)\b(?:\/\S*)?)/gi;
 const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);const nodes=[];while(w.nextNode())nodes.push(w.currentNode);
 for(const n of nodes){const t=n.nodeValue;if(!t||!t.trim())continue;const el=n.parentElement;if(!el||el.closest('#__cta'))continue;const s=t.trim();URLRX.lastIndex=0;
  if(!URLRX.test(t))continue;URLRX.lastIndex=0;
  if(s.length<70&&/^[A-Za-z0-9.\-\/:_?=&%]+$/.test(s)){el.style.visibility='hidden'}else{n.nodeValue=t.replace(URLRX,'')}}
 document.querySelectorAll('a,[role=link]').forEach(a=>{if(a.closest('#__cta'))return;const s=(a.innerText||'').trim();if(['Ad Library','Ad Library Report','Ad Library API','Branded Content','About'].includes(s))a.style.visibility='hidden'});
}"""
CTA_JS = """(link)=>{if(document.getElementById('__cta'))return;const d=document.createElement('div');d.id='__cta';
 d.style.cssText='position:fixed;left:50%;bottom:34px;transform:translateX(-50%);background:#0f172a;color:#fff;padding:16px 34px;border-radius:16px;border:3px solid #38bdf8;z-index:2147483647;text-align:center;box-shadow:0 8px 30px rgba(0,0,0,.45);display:none;font-family:Arial,Helvetica,sans-serif';
 const a=document.createElement('div');a.textContent='Sign up in 2 minutes';a.style.cssText='font:600 20px Arial;color:#7dd3fc';const b=document.createElement('div');b.textContent=link;b.style.cssText='font:700 33px Arial;margin-top:6px;letter-spacing:.2px';
 d.appendChild(a);d.appendChild(b);document.body.appendChild(d)}"""


def record(pg, pid, seconds, mp3, out_mp4, log, fps=10, link=SIGNUP_LINK, show_from=None):
    """Scrolls the active view smoothly for `seconds` and stitches the frames with the narration. No loading screens, no cursor, no face."""
    pg.goto(view_url(pid, "active"), wait_until="domcontentloaded")
    settle(pg, log)
    for _ in range(5):  # load the cards below before the take
        pg.mouse.wheel(0, 1000)
        pg.wait_for_timeout(900)
    pg.evaluate(STRIP_JS)      # no other web address or link text appears anywhere in the video
    pg.evaluate(CTA_JS, link)  # the sign up link, shown on screen from the call to action to the end
    pg.evaluate("window.scrollTo(0,0)")
    pg.wait_for_timeout(800)
    height = pg.evaluate("document.documentElement.scrollHeight")
    ymax = max(0, min(height - VIEWPORT["height"], 5200))
    n = max(20, int((seconds + 1.0) * fps))
    tmp = Path(tempfile.mkdtemp(prefix="advid_"))
    try:
        shown = False
        for i in range(n):
            if i % 20 == 0:
                pg.evaluate(STRIP_JS)
            if show_from is not None and not shown and i / fps >= show_from:
                pg.evaluate("document.getElementById('__cta').style.display='block'")
                shown = True
            f = i / (n - 1)
            e = f * f * (3 - 2 * f)  # ease in and out
            pg.evaluate(f"window.scrollTo(0,{int(ymax * e)})")
            pg.wait_for_timeout(60)
            pg.screenshot(path=str(tmp / f"f{i:04d}.jpg"), type="jpeg", quality=70)
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(tmp / "f%04d.jpg"), "-i", str(mp3), "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-r", "30", "-vf", "scale=1280:720", "-c:a", "aac", "-shortest", str(out_mp4)], capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError("ffmpeg failed: " + r.stderr[-200:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def make(item, voice=DEFAULT_VOICE, sender="Emmanuel", product="AI Ads Optimization", log=print, link=SIGNUP_LINK, host="loom"):
    """Returns {'ok': bool, 'reason': str, 'file': path, 'facts': {...}, 'script': str}."""
    from playwright.sync_api import sync_playwright
    OUT.mkdir(exist_ok=True)
    company = item.get("company") or ""
    domain = brand_domain(item.get("email"), item.get("web"))
    label = root_label(domain)
    if not label:
        return {"ok": False, "reason": "no domain to check the brand against"}
    first = (item.get("first") or "").strip() or "there"
    business = (item.get("business") or company or label).strip()
    log(f"[{company}] brand domain {domain}; searching the Ad Library")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            ctx = browser.new_context(viewport=VIEWPORT, locale="en-US")
            pg = ctx.new_page()
            cands = candidates(pg, domain, company, log)
            if not cands:
                return {"ok": False, "reason": f"no advertiser found in the Ad Library for {domain} or {company}"}
            chosen, rejected = None, []
            for pid, pname in cands[:3]:
                facts = inspect(pg, pid, label, log)
                facts["page_name"] = pname
                good = facts.get("ok") and facts["host_match_rate"] >= 0.5 and facts["matching_hosts"]
                log(f"  candidate {pname} ({pid}): " + (f"{len(facts['matching_hosts'])} brand domain(s), match rate {facts['host_match_rate']}, {facts['active']} active of {facts['total']}" if facts.get("ok") else facts.get("reason", "")))
                if good:
                    chosen = facts
                    break
                rejected.append(f"{pname}: ads point to {', '.join(facts.get('hosts', [])[:3]) or 'no domain'}")
            if not chosen:
                return {"ok": False, "reason": "brand check failed: " + "; ".join(rejected)[:300], "candidates": [c[1] for c in cands]}
            if chosen["active"] < 1:
                return {"ok": False, "reason": f"{chosen['page_name']} has no active ads right now ({chosen['total']} in the library), so there is nothing true to show", "facts": chosen}
            script = build_script(chosen, first, business, sender, product, host=host)
            vid = re.sub(r"[^A-Za-z0-9_-]", "", str(item.get("id") or label))[:40] or label
            mp3, mp4 = OUT / f"{vid}.mp3", OUT / f"{vid}.mp4"
            secs, cues = speak(script, voice, mp3, log)
            start = link_start(cues, secs)
            log(f"  narration {secs:.0f}s; the sign up link is on screen from {start:.0f}s; recording")
            record(pg, chosen["page_id"], secs, mp3, mp4, log, link=link, show_from=start)
            (OUT / f"{vid}.json").write_text(json.dumps({"item": {k: item.get(k) for k in ("id", "company", "email")}, "facts": chosen, "script": script, "voice": voice, "host": host, "link": link, "link_from": round(start, 1)}, indent=1), encoding="utf-8")
            try:
                mp3.unlink()
            except OSError:
                pass
            return {"ok": True, "file": str(mp4), "facts": chosen, "script": script, "seconds": round(secs), "link_from": round(start, 1)}
        finally:
            browser.close()


if __name__ == "__main__":
    it = json.loads(sys.argv[1])
    print(json.dumps(make(it, log=lambda m: print(m, file=sys.stderr)), indent=1))
