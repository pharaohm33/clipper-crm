#!/usr/bin/env python3
"""
Is this a real, usable contact address? Run BEFORE any clip or email is made for a lead.

    python3 tools/email_check.py name@site.com [more addresses]

classify() returns {"ok": bool, "level": "good" | "weak" | "bad", "why": text}
  bad  : cannot work (bad format, disposable, no mail server, a hosting platform's relay address such as anchor.fm, gibberish)
  weak : exists, but unlikely to reach a decision maker (support@, admin@, billing@, noreply@ ...)
  good : looks like a real contact
best(first, others) picks the best usable address from a list, preferring good over weak and never returning a bad one.
"""
import re
import subprocess
import sys

DISPOSABLE = {"mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "temp-mail.org", "yopmail.com", "trashmail.com", "sharklasers.com",
              "getnada.com", "maildrop.cc", "throwawaymail.com", "dispostable.com", "fakeinbox.com", "mailnesia.com", "mintemail.com", "spamgourmet.com"}
# addresses a hosting platform makes up for a show: mail goes to the platform, not to the host
RELAY_DOMAINS = {"anchor.fm", "podcasters.spotify.com", "spotifyforpodcasters.com", "buzzsprout.com", "libsyn.com", "podbean.com", "transistor.fm", "simplecast.com",
                 "captivate.fm", "megaphone.fm", "omnystudio.com", "acast.com", "podomatic.com", "castos.com", "blubrry.com", "redcircle.com", "ausha.io", "feedpress.it"}
WEAK_LOCAL = re.compile(r"^(support|help|helpdesk|admin|administrator|billing|accounts?|noreply|no-reply|donotreply|do-not-reply|postmaster|abuse|webmaster|privacy|legal|hr|jobs|careers|unsubscribe|mailer-daemon|notifications?|newsletter|sales-?team)$", re.I)
SYNTAX = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
_mx = {}


def has_mx(domain):
    if domain in _mx:
        return _mx[domain]
    ok = True
    try:
        out = subprocess.run(["nslookup", "-type=mx", domain], capture_output=True, text=True, timeout=12).stdout.lower()
        if "mail exchanger" in out:
            ok = True
        elif any(x in out for x in ("nxdomain", "can't find", "non-existent")):
            ok = False
        else:  # no MX: a plain A record still receives mail
            a = subprocess.run(["nslookup", domain], capture_output=True, text=True, timeout=12).stdout.lower()
            ok = "address" in a.split("non-authoritative", 1)[-1] and "nxdomain" not in a
    except Exception:
        ok = True  # lookup trouble is not proof the address is bad
    _mx[domain] = ok
    return ok


def classify(addr):
    a = str(addr or "").strip().lower()
    if not SYNTAX.match(a):
        return {"ok": False, "level": "bad", "why": "not a valid email format"}
    local, _, dom = a.partition("@")
    if dom in DISPOSABLE:
        return {"ok": False, "level": "bad", "why": "disposable mailbox"}
    if any(dom == r or dom.endswith("." + r) for r in RELAY_DOMAINS):
        return {"ok": False, "level": "bad", "why": f"a relay address made by {dom}, not a person's inbox"}
    if re.search(r"\+[0-9a-f]{6,}$", local) or re.fullmatch(r"[0-9a-f]{12,}", local) or re.search(r"(asdf|qwer|zxcv)", local):
        return {"ok": False, "level": "bad", "why": "looks auto generated or keyboard mashing"}
    if not has_mx(dom):
        return {"ok": False, "level": "bad", "why": "the domain has no mail server"}
    if WEAK_LOCAL.match(local):
        return {"ok": True, "level": "weak", "why": f"a {local}@ address rarely reaches the person who decides"}
    return {"ok": True, "level": "good", "why": "looks like a real contact"}


def best(first, others=()):
    """(address, classification) for the best usable address, or ('', None) when none is usable. Weak is used only when nothing better exists."""
    seen, cands = set(), []
    for e in [first, *others]:
        e = str(e or "").strip().lower()
        if e and e not in seen:
            seen.add(e)
            cands.append((e, classify(e)))
    good = [c for c in cands if c[1]["level"] == "good"]
    weak = [c for c in cands if c[1]["level"] == "weak"]
    return (good or weak or [("", None)])[0]


if __name__ == "__main__":
    for x in sys.argv[1:]:
        print(x, classify(x))
