#!/usr/bin/env python3
"""
Finds more leads in YOUR HALCRUS agency portal (https://agency.halcrus.ai/leads), the same page you read by hand.

It drives a real Chrome window with its OWN saved profile (tools/.halcrus_profile, kept out of the repo), so it never touches your everyday Chrome.
You log in once in that window ("Connect Halcrus" in the CRM); the portal remembers it. Nothing is written to the portal, it only reads the table.

For the chosen tier (Hot by default) it pages through the table with the page's own Next button and keeps a lead only if it
  - has an email,
  - is not marked "weaker fit" by the portal,
  - is not already in the CRM (same email, same company, same email domain) and not an earlier pick in this run, and
  - does not share a brand domain with another pick.
It remembers which page it reached (tools/halcrus_state.json), so the next run starts where this one stopped.

    python3 tools/halcrus_leads.py login
    python3 tools/halcrus_leads.py fetch 10 [Hot|Warm|Nurture]
"""
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILE = HERE / ".halcrus_profile"
SESSION = HERE / "halcrus_session.json"
STATE = HERE / "halcrus_state.json"
URL = "https://agency.halcrus.ai/leads"
FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com", "live.com", "msn.com", "me.com", "protonmail.com", "ymail.com"}

# Reads the rows of the table on screen: contact, role, email(s), company, category, intent ("98 · Hot") and the portal's reason text.
PARSE_JS = r"""() => [...document.querySelectorAll('tbody tr')].map(tr => {
  const cells = [...tr.querySelectorAll('td')].map(td => td.innerText.trim());
  const first = (cells[0] || '').split('\n').map(s => s.trim()).filter(Boolean);
  const emails = first.filter(s => /@/.test(s));
  const other = (cells[0] || '').match(/Other store emails:\s*([^\n]+)/);
  const name = first.find(s => s !== '—' && !/@|Owner|Other store/.test(s)) || '';
  return {name, email: emails[0] || '', others: other ? other[1].split(';').map(s => s.trim()).filter(Boolean) : [],
          company: cells[1] || '', category: cells[2] || '', intent: cells[3] || '', why: cells[4] || ''};
})"""
PAGE_JS = "() => (document.body.innerText.match(/Page \\d+ of [\\d,]+/) || [''])[0]"
# the total count plus the page count: both change when a tier filter has really been applied
SIG_JS = "() => ((document.body.innerText.match(/[\\d,]+ leads/) || [''])[0]) + '|' + ((document.body.innerText.match(/Page \\d+ of [\\d,]+/) || [''])[0])"


class NotLoggedIn(Exception):
    pass


def _ctx(p, show):
    PROFILE.mkdir(exist_ok=True)
    return p.chromium.launch_persistent_context(str(PROFILE), channel="chrome", headless=not show, viewport={"width": 1400, "height": 900},
                                                args=["--disable-blink-features=AutomationControlled"])


def connected():
    try:
        d = json.loads(SESSION.read_text(encoding="utf-8"))
        return bool(d.get("ok")), d.get("at", 0)
    except Exception:
        return False, 0


def _mark(ok):
    SESSION.write_text(json.dumps({"ok": ok, "at": int(time.time())}), encoding="utf-8")


def _state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(tier, page):
    d = _state()
    d[tier] = page
    STATE.write_text(json.dumps(d), encoding="utf-8")


def _table_ready(page, timeout_ms):
    try:
        page.wait_for_selector("tbody tr td", timeout=timeout_ms)
        return True
    except Exception:
        return False


def _login_state(ctx, page, host):
    """What the login window is doing: 'closed' (the window was closed), 'ready' (the lead table is showing), 'in' (signed in but on another page of the portal,
    for example its overview), or 'wait' (still at the login page)."""
    try:
        if page.is_closed() or not ctx.pages:
            return "closed"
        if _table_ready(page, 1500):
            return "ready"
        url = page.url or ""
        if host and host in url and not re.search(r"login|sign-?in|auth|register|sign-?up|forgot|reset|verify|password", url, re.I):
            return "in"
    except Exception:
        return "closed"
    return "wait"


def login(timeout=600, log=print, url=URL, show=True):
    """Opens the portal in a visible window and waits until you are logged in. Logged in means the lead table shows, or you landed on another page of the portal
    (then it opens the leads page itself). It closes the window by itself; if you close it first it stops at once and says so."""
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright
    host = urlparse(url).netloc
    with sync_playwright() as p:
        ctx = _ctx(p, show)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(url, wait_until="domcontentloaded")
            log("Log in to HALCRUS in the Chrome window that opened. It closes by itself when you are in, so leave it open until then.")
            end = time.time() + timeout
            while time.time() < end:
                st = _login_state(ctx, page, host)
                if st == "closed":
                    _mark(False)
                    log("The window was closed before the login finished. Press Connect HALCRUS again and leave the window open until it closes by itself.")
                    return False
                if st == "in":
                    try:
                        page.goto(url, wait_until="domcontentloaded")
                    except Exception:
                        pass
                    st = "ready" if _table_ready(page, 20000) else "wait"
                if st == "ready":
                    _mark(True)
                    log("HALCRUS is connected.")
                    return True
                time.sleep(1)
            _mark(False)
            log("Timed out waiting for the login.")
            return False
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def _page_no(page):
    m = re.search(r"Page (\d+) of ([\d,]+)", page.evaluate(PAGE_JS) or "")
    return (int(m.group(1)), int(m.group(2).replace(",", ""))) if m else (0, 0)


def _next(page):
    """Clicks the page's own Next button and waits for the page number to change. False when there is no next page."""
    before = page.evaluate(PAGE_JS)
    btn = page.locator("button", has_text=re.compile(r"^\s*next", re.I)).first
    if btn.count() == 0 or btn.is_disabled():
        return False
    btn.click()
    for _ in range(60):
        time.sleep(0.25)
        if page.evaluate(PAGE_JS) != before:
            break
    time.sleep(0.45)
    return True


def _domain(email):
    return email.split("@")[-1].lower().strip()


def fetch(want, known_emails=(), known_companies=(), tier="Hot", log=print, url=URL, max_pages=40, start_page=None, show=False):
    """Returns up to `want` new leads: [{email, name, others, company, category, score, tier, why, page}]. Raises NotLoggedIn if the portal asks for a login."""
    from playwright.sync_api import sync_playwright
    emails = {e.lower() for e in known_emails if e}
    companies = {re.sub(r"[^a-z0-9]", "", c.lower()) for c in known_companies if c}
    domains = {_domain(e) for e in emails if "@" in e} - FREE_MAIL
    found = []
    with sync_playwright() as p:
        ctx = _ctx(p, show)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(url, wait_until="domcontentloaded")
            if not _table_ready(page, 30000):
                _mark(False)
                raise NotLoggedIn("HALCRUS is not logged in")
            _mark(True)
            if tier and tier != "All":
                sel = page.locator("select").first
                if (sel.evaluate("e => e.selectedOptions[0].text") or "").strip() != tier:
                    before = page.evaluate(SIG_JS)
                    sel.select_option(label=tier)
                    for _ in range(80):  # wait up to 20 s for the filtered list to arrive: the counts change when it has
                        time.sleep(0.25)
                        if page.evaluate(SIG_JS) != before:
                            break
                    time.sleep(0.8)
            target = int(start_page or _state().get(tier, 1))
            cur, last = _page_no(page)
            while cur < target and _next(page):  # jump to where the last run stopped
                cur = _page_no(page)[0]
            log(f"Reading the {tier} tier of the portal, starting at page {cur} of {last or '?'}")
            scanned = 0
            while scanned < max_pages and len(found) < want:
                cur, last = _page_no(page)
                rows = page.evaluate(PARSE_JS)
                for r in rows:
                    em, co = (r["email"] or "").lower().strip(), r["company"].strip()
                    key = re.sub(r"[^a-z0-9]", "", co.lower())
                    t = re.search(r"Hot|Warm|Nurture", r["intent"])
                    if tier and tier != "All" and t and t.group(0) != tier:  # safety net: only the tier that was asked for, whatever the dropdown did
                        continue
                    if not em or not co or em in emails or key in companies or _domain(em) in domains or "weaker fit" in r["why"].lower():
                        continue
                    found.append({"email": em, "name": r["name"], "others": r["others"], "company": co, "category": r["category"],
                                  "score": int((re.search(r"\d+", r["intent"]) or [0])[0] or 0) if re.search(r"\d+", r["intent"]) else 0,
                                  "tier": t.group(0) if t else "", "why": r["why"], "page": cur})
                    emails.add(em)
                    companies.add(key)
                    domains.add(_domain(em))
                    if len(found) >= want:
                        break
                scanned += 1
                log(f"  page {cur}: {len(found)} new lead(s) so far")
                if len(found) >= want or not _next(page):
                    break
            _save_state(tier, _page_no(page)[0] if len(found) >= want else _page_no(page)[0])
        finally:
            ctx.close()
    return found


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["login"]:
        sys.exit(0 if login() else 1)
    if a[:1] == ["fetch"]:
        leads = fetch(int(a[1]) if len(a) > 1 else 5, tier=a[2] if len(a) > 2 else "Hot", log=lambda m: print(m, file=sys.stderr))
        print(json.dumps(leads, indent=1))
    else:
        print(__doc__)
