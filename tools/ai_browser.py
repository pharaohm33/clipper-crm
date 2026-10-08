#!/usr/bin/env python3
"""
One Chrome window for Google AI that STAYS OPEN between runs.

Chrome is started once with a debugging port and its own profile (the same one the Google AI tools always used, so a Google
verification you solved earlier is remembered). Every lead search or fit check connects to that window, reuses its tab, and then
only disconnects, so the window is still there for the next job. Close it yourself whenever you like, or press the button in the CRM.
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PORT = int(os.getenv("AI_BROWSER_PORT", "9223"))
PROFILE = Path.home() / ".clipper_chrome_profile"
CHROME_PATHS = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium", "chrome"]


def alive():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=2).read()
        return True
    except Exception:
        return False


def ensure_chrome():
    """Starts the long lived Chrome if it is not running yet. Returns True when it is ready."""
    if alive():
        return True
    exe = next((p for p in CHROME_PATHS if os.path.exists(p)), None)
    if not exe:
        return False
    PROFILE.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([exe, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check",
                      "--window-size=1200,900", "https://www.google.com/"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(40):
        time.sleep(0.5)
        if alive():
            return True
    return False


def get_page(p):
    """(browser, context, page). Reuses the open window and its Google tab. Falls back to a normal one-off Chrome if the long lived one cannot start.
    Always finish with release(browser): that disconnects without closing the window."""
    if ensure_chrome():
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        pages = [pg for pg in ctx.pages if not pg.url.startswith("devtools")]
        page = next((pg for pg in pages if "google." in pg.url), pages[0] if pages else ctx.new_page())
        try:
            page.bring_to_front()
        except Exception:
            pass
        return browser, ctx, page
    print("  (could not keep a Chrome window open, using a temporary one)")
    ctx = p.chromium.launch_persistent_context(str(PROFILE), channel="chrome", headless=False, viewport={"width": 1200, "height": 900})
    return ctx, ctx, (ctx.pages[0] if ctx.pages else ctx.new_page())


def release(browser):
    """Disconnects. The Chrome window keeps running. (For the temporary fallback window this closes it.)"""
    try:
        browser.close()
    except Exception:
        pass


def close_window():
    """Quits the long lived Chrome (the CRM button for 'close the Google AI window')."""
    if not alive():
        return False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
            try:
                b.new_browser_cdp_session().send("Browser.close")
            except Exception:
                pass
    except Exception:
        pass
    return not alive()
