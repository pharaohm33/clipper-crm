#!/usr/bin/env python3
"""
Is this email address one we may send to? Used for leads that come from the HALCRUS portal, whose emails are trusted to be usable.

    python3 tools/email_ai_check.py leads.json [--no-ai]       # leads.json = [{"id","email","company","web"}, ...]

Prints one 'EMAILCHECK {json}' line per lead: {id, email, valid, level, why, ai, reason}
  1. the local check (tools/email_check.py): format, disposable addresses, a relay address, no mail server. A bad one is final: valid false.
     Generic inboxes (info@, support@) are fine here: they are what the portal mostly has.
  2. unless --no-ai: Google AI Mode in the helper's Google Chrome window (no key, no quota) is asked whether the address is a real, working
     business contact address for the company. valid is false only when Google AI says so; "unknown" or no answer keeps the address (valid true).
It never solves a Google verification: if Google asks, the answer is skipped and the address is kept.
"""
import json
import random
import re
import sys
import time

import email_check


BATCH = 5  # addresses per question to Google AI: one answer covers all of them, so ten emails take two questions instead of ten


def build_prompt(items):
    """One single line (a line break would be typed as Enter and cut the question off)."""
    if isinstance(items, dict):
        items = [items]
    lst = "; ".join(f"{i + 1}) {it['email']} for the company \"{it.get('company')}\"{' (website ' + it['web'] + ')' if it.get('web') else ''}" for i, it in enumerate(items))
    return (f"For each of these {len(items)} email addresses, is it a real, working business contact address for the company named next to it? {lst}. "
            "Judge only from what you can find: the company's own website, business listings and directories, and whether the domain clearly belongs to that company. "
            "A generic inbox such as info@ or support@ on the company's own domain is fine. Do not guess: say unknown when you cannot tell. "
            "End your answer with one line of JSON per address, each with the keys email (the exact address), valid (true, false or \"unknown\") and reason (one short sentence).")


def parse(text, email=""):
    """The last JSON object in the answer that has a valid key and is about this address."""
    found = None
    for m in re.finditer(r"\{[^{}]*\"valid\"[^{}]*\}", text or "", re.S):
        try:
            o = json.loads(re.sub(r",\s*}", "}", m.group(0)))
        except Exception:
            continue
        if "|" in str(o.get("valid", "")):  # the echoed question holds a template, not an answer
            continue
        if email and str(o.get("email", "")).strip().lower() not in ("", email.lower()):
            continue
        found = o
    return found


def verdict(o):
    v = str((o or {}).get("valid", "")).strip().lower()
    return True if v == "true" else False if v == "false" else None


JITBIT = "https://www.jitbit.com/listcleaner/"


def jitbit_clean(addresses, log=print):
    """Runs the addresses through Jitbit's free Email List Cleaner (its checks run inside the page: malformed, typos, duplicates, gibberish like asdf, disposable
    mailboxes, domains with no mail server). Returns the set of addresses it KEPT, or None when the page did not answer. It cannot tell whether a mailbox exists."""
    from playwright.sync_api import sync_playwright
    addresses = [a for a in addresses if a]
    if not addresses:
        return set()
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True)
            try:
                pg = b.new_context(viewport={"width": 1200, "height": 900}).new_page()
                pg.goto(JITBIT, wait_until="domcontentloaded", timeout=30000)
                box = pg.locator("textarea").first
                box.fill("\n".join(addresses))
                pg.get_by_role("button", name=re.compile(r"clean the list", re.I)).first.click()
                pg.wait_for_function("() => /Done\\. The textbox has only valid emails now/.test(document.body.innerText)", timeout=120000)
                kept = {x.strip().lower() for x in box.input_value().splitlines() if x.strip()}
                return kept
            finally:
                b.close()
    except Exception as e:
        log("  (Jitbit List Cleaner could not be used: " + str(e).splitlines()[0][:100] + ")")
        return None


def emit(r):
    print("EMAILCHECK " + json.dumps(r), flush=True)


def main():
    items = json.load(open(sys.argv[1], encoding="utf-8"))
    use_ai = "--no-ai" not in sys.argv
    sess = p_ctx = None
    out = []
    for it in items:
        c = email_check.classify(it.get("email"))
        r = {"id": it["id"], "email": it.get("email"), "valid": bool(c["ok"]), "level": c["level"], "why": c["why"], "ai": False, "reason": ""}
        out.append(r)
        emit(r)  # the quick check is final for a bad address and is reported at once, so nothing is lost if the AI part is cut short
    if "--no-jitbit" not in sys.argv:
        cand = [r for r in out if r["valid"]]
        print(f"[jitbit] cleaning {len(cand)} address(es) with Jitbit List Cleaner ...", flush=True)
        kept = jitbit_clean([str(r["email"]).strip().lower() for r in cand], log=lambda m: print(m, flush=True))
        if kept is not None:
            for r in cand:
                if str(r["email"]).strip().lower() not in kept:
                    r["valid"], r["level"], r["why"] = False, "bad", "Jitbit List Cleaner removed it (typo, gibberish, disposable or no mail server)"
                    emit(r)
    todo = [r for r in out if r["valid"]]
    if use_ai and todo:
        try:
            import ai_browser as AB
            import google_ai_to_crm as G
            from playwright.sync_api import sync_playwright
            p_ctx = sync_playwright().start()
            sess = AB.Session(p_ctx)
            by_id = {str(it["id"]): it for it in items}
            groups = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
            for n, grp in enumerate(groups):
                its = [by_id[str(r["id"])] for r in grp]
                print(f"[{n + 1}/{len(groups)}] asking Google AI about {len(its)} address(es) ...", flush=True)
                try:
                    data = sess.ask(G.ask_google_ai, build_prompt(its))
                    text = (data or {}).get("text", "")
                except Exception as e:
                    print("  (Google AI could not be asked: " + str(e)[:100] + ")", flush=True)
                    text = ""
                for r, it in zip(grp, its):
                    o = parse(text, it["email"])
                    v = verdict(o)
                    r["ai"] = o is not None
                    if o is not None:
                        r["reason"] = str(o.get("reason", ""))[:160]
                    if v is False:
                        r["valid"], r["why"] = False, "Google AI says it is not a working address: " + (r["reason"] or "no reason given")
                    emit(r)
                if n < len(groups) - 1:
                    time.sleep(random.uniform(8, 16))
        except Exception as e:
            print("  (the Google AI check was skipped: " + str(e)[:120] + ")", flush=True)
        finally:
            try:
                if sess:
                    sess.release()
                if p_ctx:
                    p_ctx.stop()
            except Exception:
                pass
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
