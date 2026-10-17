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


def build_prompt(it):
    web = f", website {it['web']}" if it.get("web") else ""
    return (f"Is the email address \"{it['email']}\" a real, working business contact address for the company \"{it.get('company')}\"{web}? Judge only from what you can find: "
            "the company's own website, business listings and directories, and whether the domain clearly belongs to this company. A generic inbox such as info@ or support@ on the company's own domain is fine. "
            "Do not guess: say unknown when you cannot tell. End your answer with exactly one line of JSON with these keys: "
            "email (the exact address you are answering about), valid (true, false or \"unknown\"), reason (one short sentence).")


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


def main():
    items = json.load(open(sys.argv[1], encoding="utf-8"))
    use_ai = "--no-ai" not in sys.argv
    sess = p_ctx = None
    out = []
    for it in items:
        c = email_check.classify(it.get("email"))
        out.append({"id": it["id"], "email": it.get("email"), "valid": bool(c["ok"]), "level": c["level"], "why": c["why"], "ai": False, "reason": ""})
    todo = [r for r, it in zip(out, items) if r["valid"]]
    if use_ai and todo:
        try:
            import ai_browser as AB
            import google_ai_to_crm as G
            from playwright.sync_api import sync_playwright
            p_ctx = sync_playwright().start()
            sess = AB.Session(p_ctx)
            by_id = {str(it["id"]): it for it in items}
            for n, r in enumerate(todo):
                it = by_id[str(r["id"])]
                print(f"[{n + 1}/{len(todo)}] asking Google AI about {it['email']} ...", flush=True)
                try:
                    data = sess.ask(G.ask_google_ai, build_prompt(it))
                    o = parse((data or {}).get("text", ""), it["email"])
                except Exception as e:
                    print("  (Google AI could not be asked: " + str(e)[:100] + ")", flush=True)
                    o = None
                v = verdict(o)
                r["ai"] = o is not None
                if o is not None:
                    r["reason"] = str(o.get("reason", ""))[:160]
                if v is False:
                    r["valid"], r["why"] = False, "Google AI says it is not a working address: " + (r["reason"] or "no reason given")
                if n < len(todo) - 1:
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
    for r in out:
        print("EMAILCHECK " + json.dumps(r), flush=True)
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
