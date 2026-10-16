#!/usr/bin/env python3
"""
Uploads an approved video to YOUR Loom account and gives it the same two things your hand-made videos have:

  - a comment holding your sign up link, posted near the END of the video (Loom timestamps a comment at the moment you post it)
  - Loom's own clickable link chip on the player, which Loom creates by itself from a link in a comment
  - a clean title, so the viewer does not see a file name

and returns the loom.com/share link for the email.

It drives a real Chrome window with its OWN saved profile (tools/.loom_profile, kept out of the repo), so it never touches your everyday Chrome.
You log in to Loom once in that window ("Connect Loom" in the CRM); Loom remembers it. Nothing else of yours is read.

    python3 tools/loom_upload.py login
    python3 tools/loom_upload.py upload <video.mp4> "<title>" "<comment text>" [--show]
"""
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILE = HERE / ".loom_profile"
SESSION = HERE / "loom_session.json"
DEBUG = HERE / "loom_debug"
LIBRARY = "https://www.loom.com/looms/videos"


class NotLoggedIn(Exception):
    pass


def _ctx(p, show):
    PROFILE.mkdir(exist_ok=True)
    return p.chromium.launch_persistent_context(str(PROFILE), channel="chrome", headless=not show, viewport={"width": 1400, "height": 900},
                                                args=["--disable-blink-features=AutomationControlled"])


def _snap(page, name):
    try:
        DEBUG.mkdir(exist_ok=True)
        page.screenshot(path=str(DEBUG / f"{name}.png"))
    except Exception:
        pass


def connected():
    try:
        d = json.loads(SESSION.read_text(encoding="utf-8"))
        return bool(d.get("ok")), d.get("at", 0)
    except Exception:
        return False, 0


def _mark(ok):
    SESSION.write_text(json.dumps({"ok": ok, "at": int(time.time())}), encoding="utf-8")


def login(timeout=600, log=print):
    """Opens a visible Chrome window on Loom's login page and waits until you are in. Never sees or stores your password: Loom keeps the session in the profile."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = _ctx(p, True)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(LIBRARY, wait_until="domcontentloaded")
            log("A Chrome window opened. Log in to Loom there. It closes by itself when you are in.")
            end = time.time() + timeout
            while time.time() < end:
                page.wait_for_timeout(2000)
                if re.search(r"loom\.com/(looms|home|spaces|share|settings)", page.url) and not re.search(r"login|signin|sso", page.url):
                    try:
                        page.get_by_role("button", name=re.compile(r"New video", re.I)).first.wait_for(timeout=4000)
                        _mark(True)
                        log("Loom is connected.")
                        return True
                    except Exception:
                        continue
            _mark(False)
            log("Timed out waiting for the Loom login.")
            return False
        finally:
            ctx.close()


def _open_library(page):
    page.goto(LIBRARY, wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    if re.search(r"login|signin|sso", page.url):
        _mark(False)
        raise NotLoggedIn("Loom asked for a login: press Connect Loom in the CRM")


def _find_card_link(page, token):
    """The /share/ link of the library card whose title holds the token (Loom names an uploaded video after its file)."""
    return page.evaluate("""(tok)=>{const links=[...document.querySelectorAll('a[href*="/share/"]')];
      for(const a of links){const card=a.closest('div[class]')||a;let n=a,txt='';for(let i=0;i<6&&n;i++){txt=(n.innerText||'');if(txt.includes(tok))return a.href.split('?')[0];n=n.parentElement}}return ''}""", token)


def upload_and_comment(video, title, comment, show=False, log=print):
    """Returns {'ok': True, 'link': 'https://www.loom.com/share/...'} or {'ok': False, 'error': '...'}."""
    from playwright.sync_api import sync_playwright
    video = Path(video)
    if not video.exists():
        return {"ok": False, "error": f"the video file is missing: {video}"}
    token = re.sub(r"[^A-Za-z0-9]", "", video.stem)[:24] or "advideo"
    staged = HERE / f"{token}.mp4"  # Loom titles the upload after the file, so the file carries a unique token we can find again
    if staged != video:
        staged.write_bytes(video.read_bytes())
    try:
        with sync_playwright() as p:
            ctx = _ctx(p, show)
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                _open_library(page)
                log("  opening the upload box")
                page.get_by_role("button", name=re.compile(r"^New video$", re.I)).first.click(timeout=8000)
                page.wait_for_timeout(600)
                try:
                    page.get_by_text(re.compile(r"Upload a video", re.I)).first.click(timeout=4000)
                except Exception:
                    pass
                page.wait_for_selector("input.uppy-Dashboard-input", state="attached", timeout=10000)
                page.locator("input.uppy-Dashboard-input").first.set_input_files(str(staged))
                page.wait_for_timeout(1500)
                for pat in (r"^Upload (1 )?file", r"^Upload$", r"^Start upload", r"^Done$"):  # the dialog may need a confirm click
                    try:
                        page.get_by_role("button", name=re.compile(pat, re.I)).first.click(timeout=2500)
                        break
                    except Exception:
                        continue
                log("  uploading; waiting for it to appear in the library")
                link = ""
                for _ in range(80):  # up to about 6 minutes
                    page.wait_for_timeout(4500)
                    try:
                        page.goto(LIBRARY, wait_until="domcontentloaded")
                        page.wait_for_timeout(2500)
                    except Exception:
                        continue
                    link = _find_card_link(page, token)
                    if link:
                        break
                if not link:
                    _snap(page, "upload_not_found")
                    return {"ok": False, "error": "the upload did not show up in your Loom library in time (see tools/loom_debug)"}
                log("  uploaded: " + link)
                page.goto(link, wait_until="domcontentloaded")
                page.wait_for_timeout(5000)
                # a clean title
                try:
                    h = page.locator("h1").first
                    h.click(timeout=3000)
                    page.keyboard.press("Meta+A" if sys.platform == "darwin" else "Control+A")
                    page.keyboard.type(title)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(1200)
                except Exception:
                    log("  (could not rename the video, left the file name as the title)")
                # near the end: seek, pause, then comment (Loom stamps the comment with the current time)
                dur = 0.0
                for _ in range(30):
                    dur = page.evaluate("(()=>{const v=document.querySelector('video');return v&&isFinite(v.duration)?v.duration:0})()") or 0
                    if dur > 3:
                        break
                    page.wait_for_timeout(2000)
                if dur > 3:
                    page.evaluate("(d)=>{const v=document.querySelector('video');v.pause();v.currentTime=Math.max(0,d-8)}", dur)
                    page.wait_for_timeout(1500)
                box = page.get_by_placeholder(re.compile(r"Leave a comment", re.I)).first
                box.click(timeout=8000)
                page.wait_for_timeout(500)
                page.keyboard.type(comment, delay=25)
                page.wait_for_timeout(600)
                page.keyboard.press("Enter")
                domain = re.sub(r"^https?://", "", comment).split("/")[0]
                posted = False
                for _ in range(10):
                    page.wait_for_timeout(1500)
                    if domain and domain in page.inner_text("body").replace("\n", " ") and page.locator("a[href*='" + domain + "']").count() > 0:
                        posted = True
                        break
                if not posted:
                    _snap(page, "comment_not_posted")
                    return {"ok": False, "error": "the video uploaded but the comment with the link could not be confirmed (see tools/loom_debug)", "link": link}
                chip = page.locator("a[href*='" + domain + "']").count() > 1
                return {"ok": True, "link": link, "duration": round(dur), "chip_seen": bool(chip)}
            finally:
                ctx.close()
    except NotLoggedIn as e:
        return {"ok": False, "error": str(e), "needs_login": True}
    except Exception as e:
        return {"ok": False, "error": "Loom upload failed: " + str(e)[:200]}
    finally:
        if staged != video:
            try:
                staged.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "login":
        sys.exit(0 if login() else 1)
    if a and a[0] == "upload" and len(a) >= 4:
        print(json.dumps(upload_and_comment(a[1], a[2], a[3], show="--show" in a), indent=1))
    else:
        sys.exit(__doc__)
