#!/usr/bin/env python3
"""
When a prospect replies, DeepSeek decides whether they clearly said YES to getting the clip. If so, a reply is written
from the same inbox that sent the first email (threaded), with the link to their folder of clips and your phone number.

Safety:
- config "auto_reply": "draft" (default) saves the reply in that inbox's Drafts for you to look at and press send;
  "send" sends it right away. Start with "draft" until you trust it.
- Only a clear "yes" at 0.8+ confidence triggers anything. "No" (0.8+) adds the person to the do-not-contact list.
  Questions and anything unclear are left for you.
- Needs your phone number (config "phone", set it with setup_email.py option 3). Without it nothing is written.
- Nobody gets two auto replies.
- The link is only made public at this moment (the clips stay private drafts until then).
"""
import json
import re
import time
import urllib.error
import urllib.request

import cold_email
import personalize

APP_URL = "http://127.0.0.1:5001"
MIN_CONFIDENCE = 0.8
REPLY_BODY = ("{Awesome|Great|Perfect}, glad you want it. Here are your {name} clips, all in one place:\n\n{link}\n\n"
              "Each one comes with a title, description and hashtags, ready to post. Let me know if you like them, and if you want more, "
              "I can help you make as much content like this as you want. Just reply here or text me.\n\n{sender}\n{phone}")


def sheet_link(slug):
    """Asks the clipper app to make this template's sheet (and its clips) viewable by link. (link or '', error or '')."""
    req = urllib.request.Request(APP_URL + "/api/handoff/share", data=json.dumps({"slug": slug}).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read())
        except Exception:
            d = {}
        return "", d.get("error") or f"clipper said {e.code}"
    except Exception as e:
        return "", f"clipper app not reachable ({str(e)[:60]})"
    return (d.get("link") or ""), ("" if d.get("link") else d.get("error") or "no link came back")


def build_reply(cfg, to, name, link):
    """The exact text sent when a prospect says yes (the wording picks are fixed per recipient, so a preview matches what goes out)."""
    return (cold_email.spin(REPLY_BODY, f"reply:{to}")
            .replace("{name}", cold_email.short_name(name))
            .replace("{link}", link)
            .replace("{sender}", str(cfg.get("sender_name") or ""))
            .replace("{phone}", str(cfg.get("phone") or "")))


def preview(to, name, slug):
    """What the reply would say right now, and the handoff page link if that page already exists (it stays private until they say yes)."""
    cfg = cold_email.load_config()
    link = ""
    want = re.sub(r"[^a-z0-9]+", "", str(name or "").lower())
    for attempt in range(2):
        try:
            with urllib.request.urlopen(APP_URL + "/api/handoff/list", timeout=20) as r:
                sheets = json.loads(r.read()).get("sheets", [])
            for s in sheets:
                if s.get("link") and (s.get("slug") == slug and slug):
                    link = s["link"]
            if not link and want:  # the lead has no saved slug: match the sheet by the show's name
                for s in sheets:
                    if s.get("link") and re.sub(r"[^a-z0-9]+", "", str(s.get("name") or "").lower()) == want:
                        link = s["link"]
            break
        except Exception:
            time.sleep(1)
    shown = link or "[link to their page of clips, made public only when they say yes]"
    return {"text": build_reply(cfg, to.lower(), name, shown), "link": link, "phone_set": bool((cfg.get("phone") or "").strip())}


def already_handled(log, to):
    return any(e.get("to", "").lower() == to and e.get("status") in ("auto_replied", "auto_drafted") for e in log)


def handle(found, log_fn=print):
    """Adds 'intent' and 'auto' to each found reply and acts on clear yes/no answers. Returns the same list."""
    cfg = cold_email.load_config()
    mode = "send" if cfg.get("auto_reply") == "send" else "draft"
    for f in found:
        if f.get("kind") != "replied":
            continue
        to = f["email"].lower()
        log = cold_email.read_log()
        if already_handled(log, to):
            f["auto"] = "already answered"
            continue
        verdict = personalize.classify_reply(f.get("text", ""))
        f["intent"], f["confidence"] = verdict["intent"], verdict["confidence"]
        if verdict["confidence"] < MIN_CONFIDENCE or verdict["intent"] in ("question", "other"):
            f["auto"] = "needs you"
            continue
        if verdict["intent"] == "no":
            cold_email.suppress(to, "declined by reply")
            f["kind"], f["auto"] = "optout", "declined (added to the do not contact list)"
            continue
        # clear yes
        if not (cfg.get("phone") or "").strip():
            f["auto"] = "needs your phone number (setup_email.py option 3)"
            continue
        if not f.get("slug"):
            f["auto"] = "needs you (no clips found for this lead)"
            continue
        first = cold_email.first_mail_for(log, to) or {}
        acct = next((a for a in cfg.get("accounts", []) if a["email"] == first.get("from")), None)
        if not acct:
            f["auto"] = "needs you (the inbox that sent the first email is not set up)"
            continue
        link, err = sheet_link(f["slug"])
        if not link:
            f["auto"] = f"needs you (could not make the link: {err})"
            log_fn(f"no link for {to}: {err}")
            continue
        body = build_reply(cfg, to, f.get("name"), link)
        subject = "Re: " + (first.get("subject") or f.get("subject") or "your episode clip")
        msg = cold_email.compose(acct, cfg, to, subject, body, f.get("msgid") or first.get("message_id"))
        try:
            (cold_email.send_message if mode == "send" else cold_email.save_draft)(acct, msg)
        except Exception as e:
            f["auto"] = f"needs you (could not {'send' if mode == 'send' else 'draft'} it: {str(e)[:80]})"
            continue
        status = "auto_replied" if mode == "send" else "auto_drafted"
        cold_email.append_log({"ts": time.time(), "id": f["id"], "to": to, "from": acct["email"], "status": status, "step": 0,
                               "subject": subject, "link": link, "message_id": msg["Message-ID"]})
        f["auto"] = "sent" if mode == "send" else "drafted"
        f["link"] = link
        log_fn(f"{f['auto']} reply to {to}")
    return found
