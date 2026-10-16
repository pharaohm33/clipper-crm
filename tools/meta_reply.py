#!/usr/bin/env python3
"""
Meta ads campaign: when a prospect replies, DeepSeek decides which prepared answer fits, and the answer is saved as a DRAFT for you to approve.
It never sends by itself.

  confused         "who is this?", "what is this about?", "I didn't ask for this"          -> the confused template
  interested       wants more info, asks how it works, asks about price                   -> the interested template
  ready            clearly wants to get started or asks for the link                       -> the ready template
  not_interested   no thanks, stop, remove me                                              -> they go on the do-not-contact list, no reply
  other            out of office, a question the templates do not cover, anything unclear -> left for you

DeepSeek only CHOOSES the template and says how sure it is. The words that go out are your templates, with the fill-ins replaced, so it cannot
invent claims or prices. Anything under 0.75 confidence is left for you.
"""
import json
import re
import time
import urllib.request

import cold_email
import personalize

MIN_CONFIDENCE = 0.75
INTENTS = ("confused", "interested", "ready", "not_interested", "other")

SYSTEM = """You read a reply to a cold email. The sender (an agency) offered to cut wasted Meta (Facebook and Instagram) ad spend for the recipient's company. Pricing is performance based: the agency keeps 20% of the money it saves, and nothing if it saves nothing.
Decide what the recipient's reply means. Reply with ONLY a JSON object: {"intent": "...", "confidence": 0.0 to 1.0, "summary": "one short sentence"}

intent must be one of:
- "confused": they do not know who the sender is or what this is about, or say they did not ask for it
- "interested": they want more information, ask how it works, ask what it costs, or say it sounds interesting
- "ready": they clearly want to start, sign up or get the link
- "not_interested": they decline, are not interested, or ask to stop or be removed
- "other": out of office or automatic reply, a person who forwards it on, a detailed or unusual question, a complaint, or anything unclear

Be conservative: use "ready" only when they clearly want to start. Ignore quoted earlier messages. An automatic reply is "other"."""


def decide(text, timeout=45):
    """{'intent', 'confidence', 'summary'}. Falls back to other/0 when DeepSeek cannot be reached."""
    text = re.sub(r"\s+", " ", text or "").strip()[:1500]
    key = personalize.deepseek_key()
    if not text or not key:
        return {"intent": "other", "confidence": 0.0, "summary": "DeepSeek was not available"}
    body = json.dumps({"model": personalize.MODEL, "temperature": 0, "max_tokens": 120,
                       "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Reply:\n" + text}]}).encode()
    req = urllib.request.Request(personalize.URL, data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read())["choices"][0]["message"]["content"]
        d = json.loads(re.search(r"\{.*?\}", out, re.S).group(0))
        intent = str(d.get("intent", "other")).lower()
        return {"intent": intent if intent in INTENTS else "other", "confidence": float(d.get("confidence", 0) or 0), "summary": str(d.get("summary") or "")[:140]}
    except Exception:
        return {"intent": "other", "confidence": 0.0, "summary": "could not read DeepSeek's answer"}


def render(template_text, lead_vars, cfg, first_name):
    t = template_text.replace("{first_name}", first_name or "there").replace("{sender}", str(cfg.get("sender_name") or ""))
    for k, v in (lead_vars or {}).items():
        t = t.replace("{" + str(k) + "}", str(v))
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def handle(found, templates, lead_vars=None, log_fn=print, lead_info=None):
    """Adds 'intent', 'confidence', 'summary' and 'auto' to each reply, saves the matching answer as a draft, and honours opt-outs."""
    cfg = cold_email.load_config()
    for f in found:
        if f.get("kind") != "replied":
            continue
        to = f["email"].lower()
        log = cold_email.read_log()
        if any(e.get("to", "").lower() == to and e.get("status") in ("auto_drafted", "auto_replied") for e in log):
            f["auto"] = "already answered"
            continue
        v = decide(f.get("text", ""))
        f["intent"], f["confidence"], f["summary"] = v["intent"], v["confidence"], v["summary"]
        if v["confidence"] < MIN_CONFIDENCE or v["intent"] == "other":
            f["auto"] = "needs you"
            continue
        if v["intent"] == "not_interested":
            cold_email.suppress(to, "declined by reply (meta campaign)")
            f["kind"], f["auto"] = "optout", "declined (added to the do not contact list)"
            continue
        text = (templates or {}).get(v["intent"]) or ""
        if not text.strip():
            f["auto"] = f"needs you (no '{v['intent']}' reply template is set)"
            continue
        first = cold_email.first_mail_for(log, to) or {}
        acct = next((a for a in cfg.get("accounts", []) if a["email"] == first.get("from")), None)
        if not acct:
            f["auto"] = "needs you (the inbox that sent the first email is not set up)"
            continue
        info = (lead_info or {}).get(f.get("id")) or {}
        body = render(text, {**(lead_vars or {}), "business": info.get("business") or (lead_vars or {}).get("business") or "your company"}, cfg, info.get("first") or "there")
        subject = "Re: " + (first.get("subject") or f.get("subject") or "your Meta ads")
        msg = cold_email.compose(acct, cfg, to, subject, body, f.get("msgid") or first.get("message_id"))
        try:
            cold_email.save_draft(acct, msg)
        except Exception as e:
            f["auto"] = f"needs you (could not save the draft: {str(e)[:80]})"
            continue
        cold_email.append_log({"ts": time.time(), "id": f["id"], "to": to, "from": acct["email"], "status": "auto_drafted", "step": 0, "subject": subject,
                               "message_id": msg["Message-ID"], "campaign": "meta", "template_name": "Meta reply: " + v["intent"]})
        f["auto"] = "drafted"
        log_fn(f"drafted a '{v['intent']}' reply to {to}")
    return found
