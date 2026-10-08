#!/usr/bin/env python3
"""
Cold email engine for the clip outreach: one short, honest email per podcast with a link to a clip made from their own episode.

Built to protect your sender reputation and to follow cold email law (CAN-SPAM and similar):
  * ROTATES across your inboxes (tools/email_accounts.json), always using the one that has sent the least today
  * DAILY CAP per inbox, with a slow WARM-UP (starts small, grows each day)
  * RANDOM spacing between sends, only inside a send window (default 9am to 5pm your time)
  * NEVER emails the same address twice in 90 days, never emails anyone on tools/suppression.txt
  * Every email carries your real name, your postal address, and a plain way to opt out; replies like "no thanks" or "unsubscribe"
    are detected and the address is added to the suppression list for good
  * Modes: preview (nothing is sent), drafts (saved into the inbox's Drafts folder for you to read and send), send

You supply the inboxes (use SEPARATE sending domains, not your main one) and an app password for each. Nothing is stored anywhere but
tools/email_accounts.json on your computer (git-ignored).
"""
import email.utils
import imaplib
import json
import random
import re
import smtplib
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import os
HERE = Path(os.getenv("COLD_EMAIL_HOME") or Path(__file__).resolve().parent)
CONFIG = HERE / "email_accounts.json"
LOG = HERE / "email_log.jsonl"
SUPPRESS = HERE / "suppression.txt"
OPT_OUT = re.compile(r"\b(unsubscribe|remove me|take me off|stop (emailing|sending|contacting)|do not (email|contact)|don't (email|contact)|no thanks|not interested|please stop)\b", re.I)

DEFAULT_SUBJECT = "{Quick clip|Short clip|Clip} from your {niche} episode"
DEFAULT_BODY = """{Hi|Hey|Hello} there,

{I just watched|I caught|I watched} your recent episode on {niche} and {loved it|really enjoyed it}. I cut a short clip from it that I think could do well on Reels, TikTok and Shorts:

{clip_link}

{It is yours to post, free, no strings attached.|Feel free to post it, it is yours, no strings attached.} If you'd like a few of these each week, just reply and I'll send you more.

{Thanks|Best|Cheers},
{sender}"""
FOLLOWUPS = [
    (3, "Just floating this back up in case it got buried. The clip is yours to keep either way, and I'm happy to cut a few more from your recent episodes if that would help.\n\n{sender}"),
    (7, "Last note from me. If clips for your channel aren't a fit right now, no problem at all, just reply \"no thanks\" and I won't reach out again.\n\n{clip_link}\n\n{sender}"),
]


# ----------------------------------------------------------------------------------------- config / logs
def load_config():
    if not CONFIG.exists():
        return {"accounts": [], "_missing": True}
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def read_log():
    out = []
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def append_log(entry):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def suppressed():
    if not SUPPRESS.exists():
        return set()
    return {l.strip().lower() for l in SUPPRESS.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}


def suppress(address, why=""):
    address = address.strip().lower()
    if address and address not in suppressed():
        with open(SUPPRESS, "a", encoding="utf-8") as f:
            f.write(f"{address}\n")
        append_log({"ts": time.time(), "to": address, "status": "suppressed", "why": why})


def is_suppressed(address):
    s, a = suppressed(), address.lower()
    return a in s or "@" + a.split("@")[-1] in s


def sent_entries(log=None):
    return [e for e in (log if log is not None else read_log()) if e.get("status") in ("sent", "drafted")]


# ----------------------------------------------------------------------------------------- rotation / caps
def _day(ts):
    return datetime.fromtimestamp(ts).date()


def warm_cap(acct, cfg, log):
    w = cfg.get("warmup") or {}
    mine = [e["ts"] for e in sent_entries(log) if e.get("from") == acct["email"]]
    days_active = (datetime.now().date() - _day(min(mine))).days if mine else 0
    cap = int(w.get("start", 5)) + int(w.get("add_per_day", 3)) * days_active
    return max(1, min(cap, int(w.get("max", 30)), int(acct.get("daily_limit", 20))))


def sent_today(acct, log):
    today = datetime.now().date()
    return sum(1 for e in sent_entries(log) if e.get("from") == acct["email"] and e.get("status") == "sent" and _day(e["ts"]) == today)


def capacity(cfg, log):
    return [{"email": a["email"], "sent_today": sent_today(a, log), "cap": warm_cap(a, cfg, log)} for a in cfg.get("accounts", [])]


def pick_account(cfg, log, used=None):
    """The inbox with the most room left today (so sends spread evenly), or None when every inbox is at its cap."""
    used = used or {}
    best, room = None, 0
    for a in cfg.get("accounts", []):
        left = warm_cap(a, cfg, log) - sent_today(a, log) - used.get(a["email"], 0)
        if left > room:
            best, room = a, left
    return best


def in_window(cfg, now=None):
    now = now or datetime.now()
    w = cfg.get("send_window") or {}
    return int(w.get("start_hour", 9)) <= now.hour < int(w.get("end_hour", 17))


# ----------------------------------------------------------------------------------------- writing the email
def spin(text, seed):
    rng = random.Random(seed)
    pat = re.compile(r"\{([^{}]*\|[^{}]*)\}")
    while True:
        m = pat.search(text)
        if not m:
            return text
        text = text[:m.start()] + rng.choice(m.group(1).split("|")) + text[m.end():]


def _prose(text):
    """Plain, natural wording: no em dashes and no hyphens in the prose (links and the clip title are added afterwards)."""
    return re.sub(r"\s*[—–]\s*", ", ", text).replace("-", " ")


def render(template, lead, cfg, step=0, subject_for_reply=None):
    """(subject, body) for one lead. Spintax picks are fixed per lead, so a re-preview shows the same email that will go out."""
    seed = f"{lead.get('id')}:{step}"
    fill = lambda t: (_prose(spin(t, seed))
                      .replace("{niche}", str(lead.get("niche") or "your").replace("-", " "))
                      .replace("{name}", str(lead.get("name") or "your podcast"))
                      .replace("{episode}", str(lead.get("epTitle") or "your recent episode"))
                      .replace("{clip_link}", str(lead.get("clipLink") or lead.get("link") or ""))
                      .replace("{sender}", str(cfg.get("sender_name") or "")))
    if step == 0:
        subject, body = fill(template.get("subject") or DEFAULT_SUBJECT), fill(template.get("body") or DEFAULT_BODY)
    else:
        days, text = FOLLOWUPS[min(step, len(FOLLOWUPS)) - 1]
        subject = "Re: " + (subject_for_reply or "your episode clip")
        body = fill(template.get(f"followup{step}") or text)
    footer = f"\n\n--\n{cfg.get('sender_name', '')}\n{cfg.get('postal_address', '')}\nNot interested? Just reply \"no thanks\" and I won't email you again."
    return subject.strip(), re.sub(r"\n{3,}", "\n\n", body).strip() + footer


def compose(acct, cfg, to, subject, body, in_reply_to=None):
    msg = EmailMessage()
    msg["From"] = email.utils.formataddr((cfg.get("sender_name") or "", acct["email"]))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=acct["email"].split("@")[-1])
    if cfg.get("reply_to"):
        msg["Reply-To"] = cfg["reply_to"]
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg["List-Unsubscribe"] = f"<mailto:{acct['email']}?subject=unsubscribe>"
    msg.set_content(body)
    return msg


# ----------------------------------------------------------------------------------------- delivering it
def _smtp(acct):
    port = int(acct.get("smtp_port", 587))
    s = smtplib.SMTP_SSL(acct["smtp_host"], port, timeout=40) if port == 465 else smtplib.SMTP(acct["smtp_host"], port, timeout=40)
    if port != 465 and acct.get("tls", True):
        s.starttls()
    if acct.get("password"):
        s.login(acct.get("username") or acct["email"], acct["password"])
    return s


def send_message(acct, msg):
    with _smtp(acct) as s:
        s.send_message(msg)


def save_draft(acct, msg):
    imap = imaplib.IMAP4_SSL(acct.get("imap_host") or acct["smtp_host"].replace("smtp.", "imap."))
    try:
        imap.login(acct.get("username") or acct["email"], acct["password"])
        folder = '"[Gmail]/Drafts"' if "gmail" in (acct.get("imap_host") or acct["smtp_host"]) else "Drafts"
        imap.append(folder, "\\Draft", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
    finally:
        try:
            imap.logout()
        except Exception:
            pass


# ----------------------------------------------------------------------------------------- the run
def plan(leads, template, mode="preview", limit=20, ignore_window=False, step=0):
    """Decides, for each lead in order, what would happen. No sending. Yields dicts (status: ready/skip)."""
    cfg, log = load_config(), read_log()
    used, recent = {}, {e["to"].lower() for e in sent_entries(log) if e.get("ts", 0) > time.time() - 90 * 86400 and e.get("step", 0) == step}
    n = 0
    for ld in leads:
        to = (ld.get("email") or "").strip().lower()
        base = {"id": ld.get("id"), "name": ld.get("name"), "to": to, "step": step}
        if not to or "@" not in to:
            yield {**base, "status": "skip", "why": "no email address"}
            continue
        if is_suppressed(to):
            yield {**base, "status": "skip", "why": "on the do-not-contact list"}
            continue
        if to in recent:
            yield {**base, "status": "skip", "why": "already emailed in the last 90 days"}
            continue
        if step == 0 and not (ld.get("clipLink") or ld.get("link")):
            yield {**base, "status": "skip", "why": "no clip link yet (prepare the clip first)"}
            continue
        if n >= limit:
            yield {**base, "status": "skip", "why": f"over this run's limit of {limit}"}
            continue
        first_mail = None
        if step > 0:
            firsts = [e for e in sent_entries(log) if e.get("to", "").lower() == to and e.get("step", 0) == 0 and e.get("status") == "sent"]
            if not firsts:
                yield {**base, "status": "skip", "why": "no first email was sent to this address"}
                continue
            first_mail = firsts[-1]
            if any(e.get("to", "").lower() == to and e.get("status") in ("replied", "optout") for e in log):
                yield {**base, "status": "skip", "why": "they already replied"}
                continue
            days_needed = FOLLOWUPS[min(step, len(FOLLOWUPS)) - 1][0]
            if time.time() - first_mail["ts"] < days_needed * 86400 - 3600:
                yield {**base, "status": "skip", "why": f"too soon (follow up {days_needed} days after the first email)"}
                continue
            ld = {**ld, "subject": first_mail.get("subject", "")}
            acct = next((a for a in cfg.get("accounts", []) if a["email"] == first_mail.get("from")), None)
            if mode != "preview" and acct and warm_cap(acct, cfg, log) - sent_today(acct, log) - used.get(acct["email"], 0) <= 0:
                yield {**base, "status": "skip", "why": "that inbox is at its daily cap"}
                continue
        else:
            acct = pick_account(cfg, log, used) if mode != "preview" or cfg.get("accounts") else None
        if mode != "preview" and not acct:
            yield {**base, "status": "skip", "why": "every inbox is at its daily cap" if step == 0 else "the inbox that sent the first email is not set up"}
            continue
        if mode == "send" and not ignore_window and not in_window(cfg):
            yield {**base, "status": "skip", "why": "outside the send window"}
            continue
        subject, body = render(template, ld, cfg, step, ld.get("subject"))
        if acct:
            used[acct["email"]] = used.get(acct["email"], 0) + 1
        n += 1
        yield {**base, "status": "ready", "from": acct["email"] if acct else "(no inbox set up yet)", "subject": subject, "body": body,
               "in_reply_to": (first_mail or {}).get("message_id")}


def run(leads, template, mode, limit=20, ignore_window=False, step=0, log_fn=print, sleep=time.sleep):
    """mode 'drafts' or 'send'. Returns the list of result dicts. Sends one at a time with random spacing."""
    cfg = load_config()
    problems = []
    if not cfg.get("accounts"):
        problems.append("no sending inboxes are set up in tools/email_accounts.json")
    if not (cfg.get("postal_address") or "").strip() or "Your real mailing address" in cfg.get("postal_address", ""):
        problems.append("add your real postal address to tools/email_accounts.json (cold email law requires it in every email)")
    if not (cfg.get("sender_name") or "").strip() or cfg.get("sender_name") == "Your Name":
        problems.append("add your name as sender_name in tools/email_accounts.json")
    if problems:
        raise RuntimeError("; ".join(problems))
    results, first = [], True
    for item in plan(leads, template, mode, limit, ignore_window, step):
        if item["status"] != "ready":
            log_fn(f"skip {item['to'] or item['name']}: {item['why']}")
            results.append(item)
            continue
        if not first and mode == "send":
            sleep(random.uniform(float(cfg.get("min_delay_seconds", 90)), float(cfg.get("max_delay_seconds", 240))))
        first = False
        acct = next(a for a in cfg["accounts"] if a["email"] == item["from"])
        msg = compose(acct, cfg, item["to"], item["subject"], item["body"], item.get("in_reply_to"))
        try:
            (send_message if mode == "send" else save_draft)(acct, msg)
            status = "sent" if mode == "send" else "drafted"
        except Exception as e:
            item.update(status="failed", why=str(e)[:200])
            log_fn(f"FAILED {item['to']} via {item['from']}: {item['why']}")
            results.append(item)
            append_log({"ts": time.time(), "id": item["id"], "to": item["to"], "from": item["from"], "status": "failed", "why": item["why"], "step": item["step"]})
            continue
        entry = {"ts": time.time(), "id": item["id"], "to": item["to"], "from": item["from"], "subject": item["subject"],
                 "message_id": msg["Message-ID"], "status": status, "step": item["step"]}
        append_log(entry)
        results.append({**item, "status": status, "message_id": msg["Message-ID"]})
        log_fn(f"{status} {item['to']} via {item['from']}")
    return results


# ----------------------------------------------------------------------------------------- replies / opt outs
def check_replies(sent, log_fn=print):
    """sent: [{id, email, since_ts}]. Looks in each sending inbox for a reply from that address. Returns
    {found: [{id, email, kind: 'replied'|'optout', snippet}], errors: [...]} and adds opt-outs to the suppression list."""
    cfg, found, errors = load_config(), [], []
    by_acct = {}
    for e in sent_entries():
        by_acct.setdefault(e.get("from"), set()).add(e.get("to", "").lower())
    for acct in cfg.get("accounts", []):
        wanted = [s for s in sent if s["email"].lower() in by_acct.get(acct["email"], set())]
        if not wanted:
            continue
        try:
            imap = imaplib.IMAP4_SSL(acct.get("imap_host") or acct["smtp_host"].replace("smtp.", "imap."))
            imap.login(acct.get("username") or acct["email"], acct["password"])
            imap.select("INBOX", readonly=True)
            for s in wanted:
                since = datetime.fromtimestamp(s.get("since_ts") or time.time() - 30 * 86400).strftime("%d-%b-%Y")
                typ, data = imap.search(None, f'(FROM "{s["email"]}" SINCE {since})')
                ids = data[0].split() if typ == "OK" and data and data[0] else []
                if not ids:
                    continue
                typ, raw = imap.fetch(ids[-1], "(BODY.PEEK[TEXT]<0.1500>)")
                text = raw[0][1].decode("utf-8", "ignore") if raw and raw[0] else ""
                kind = "optout" if OPT_OUT.search(text) else "replied"
                if kind == "optout":
                    suppress(s["email"], "asked to stop")
                found.append({"id": s["id"], "email": s["email"], "kind": kind, "snippet": re.sub(r"\s+", " ", text)[:160]})
                log_fn(f"{kind}: {s['email']}")
            imap.logout()
        except Exception as e:
            errors.append(f"{acct['email']}: {str(e)[:120]}")
            log_fn(f"could not check {acct['email']}: {str(e)[:120]}")
    return {"found": found, "errors": errors}
