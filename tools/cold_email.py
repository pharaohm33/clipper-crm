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
import subprocess
import zlib
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

DEFAULT_SUBJECT = "made clips from {name}"
DEFAULT_BODY = """{Hi|Hey}, I {saw|caught|came across} {show_ref} and {really liked|loved|really enjoyed} {topic}. It stuck with me, so I went ahead and made {clips} out of it, ready for Reels, TikTok and YouTube Shorts.

{done_line} {Just reply yes and I'll send {them_it} right over.|Want me to send {them_it} over?}

{Thanks|Best|Cheers},
{sender}"""
FOLLOWUPS = [
    (3, "Just floating this back up in case it got buried. I'm still happy to send the clip over if you want it, and it costs you nothing.\n\n{sender}"),
    (7, "Last note from me. If clips aren't a fit right now, no problem at all, just reply \"no thanks\" and I won't reach out again.\n\n{sender}"),
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


_mx_cache = {}


def mx_provider(domain):
    """Who hosts this domain's mail: 'google', 'microsoft', 'other' or 'unknown' (lookup failed). Cached per domain."""
    domain = (domain or "").lower()
    if domain in _mx_cache:
        return _mx_cache[domain]
    if domain in ("gmail.com", "googlemail.com"):
        res = "google"
    elif domain in ("outlook.com", "hotmail.com", "live.com", "msn.com") or domain.startswith(("outlook.", "hotmail.", "live.")):
        res = "microsoft"
    else:
        try:
            out = subprocess.run(["nslookup", "-type=mx", domain], capture_output=True, text=True, timeout=12).stdout.lower()
            res = ("microsoft" if ("protection.outlook.com" in out or "mail.protection.outlook" in out) else
                   "google" if ("google.com" in out or "googlemail.com" in out) else
                   "other" if "mail exchanger" in out else "unknown")
        except Exception:
            res = "unknown"
    _mx_cache[domain] = res
    return res


def pick_variant(template, lead_id):
    """('A', subject, body) for this lead. template['variants'] is a list of {subject, body} that add to the base email (A).
    The pick depends only on the lead id, so preview, send and follow-ups all agree."""
    extra = [v for v in (template.get("variants") or []) if (v.get("subject") or v.get("body"))]
    options = [{"subject": template.get("subject"), "body": template.get("body")}] + [
        {"subject": v.get("subject") or template.get("subject"), "body": v.get("body") or template.get("body")} for v in extra]
    i = zlib.crc32(str(lead_id).encode()) % len(options)
    return chr(65 + i), options[i]["subject"], options[i]["body"]


def stats(log=None):
    """First-email results per variant and per recipient mail host: sent, replied, asked to stop, bounced, failed."""
    log = read_log() if log is None else log
    firsts = {}
    for e in log:
        if e.get("status") == "sent" and e.get("step", 0) == 0:
            firsts[e.get("to", "").lower()] = e
    outcome = {}
    for e in log:
        if e.get("status") in ("replied", "optout", "bounced"):
            outcome.setdefault(e.get("to", "").lower(), set()).add(e["status"])
    out = {"variant": {}, "provider": {}}
    for to, e in firsts.items():
        for kind, key in (("variant", e.get("variant") or "A"), ("provider", e.get("provider") or "unknown")):
            row = out[kind].setdefault(key, {"sent": 0, "replied": 0, "optout": 0, "bounced": 0})
            row["sent"] += 1
            for st in outcome.get(to, ()):
                row[st] += 1
    for kind in out:
        for row in out[kind].values():
            row["reply_rate"] = round(100 * row["replied"] / row["sent"], 1) if row["sent"] else 0
    return out


def sent_entries(log=None):
    """Real sends only. A draft is not a send: it must not count toward the 90 day rule, the warm-up ramp or reply checks."""
    return [e for e in (log if log is not None else read_log()) if e.get("status") == "sent"]


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
    return [{"email": a["email"], "sent_today": sent_today(a, log), "cap": 0 if a.get("paused") else warm_cap(a, cfg, log), "paused": bool(a.get("paused"))}
            for a in cfg.get("accounts", [])]


def pick_account(cfg, log, used=None):
    """The inbox with the most room left today (so sends spread evenly), or None when every inbox is at its cap."""
    used = used or {}
    best, room = None, 0
    for a in cfg.get("accounts", []):
        if a.get("paused"):
            continue  # a paused inbox is kept for later but never picked for a send
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


def short_name(name):
    """The show's name as a person would say it, not the full channel title.
    'D.J. Paris - Keeping It Real Podcast' -> 'Keeping It Real Podcast', 'Rosemary Lewis | Real Estate Coach' -> 'Rosemary Lewis',
    'ActionCOACH Business Coaching UK' -> 'ActionCOACH', 'The Real Estate Guys Radio Show' -> 'The Real Estate Guys'."""
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    parts = [p.strip() for p in re.split(r"\s*[|\u2013\u2014:]\s*|\s+-\s+|-\s+", name) if p.strip()]
    if len(parts) > 1:
        named = [p for p in parts if re.search(r"podcast|\bshow\b|radio|\btalk\b|cast\b", p, re.I)]
        name = (named or parts)[0]
    region = re.compile(r"\s+(UK|U\.K\.|US|USA|U\.S\.|AU|CA|Canada|Australia|Official|HD|TV|Channel)$", re.I)
    tail = re.compile(r"\s+(business coaching|business coach|business consulting|coaching|consulting|consultants?|official channel|official|channel|"
                      r"media|network|academy|group|llc|inc\.?|company|radio show|show|radio)$", re.I)
    words = name.split()
    while len(words) > 1 and region.search(" ".join(words)):
        words = region.sub("", " ".join(words)).split()
    while len(words) > 2 and tail.search(" ".join(words)):
        words = tail.sub("", " ".join(words)).split()
    if len(words) > 5:  # still very long: keep the first few words, never ending on a joining word
        words = words[:4]
        while len(words) > 1 and words[-1].lower() in ("and", "of", "to", "the", "for", "with", "in", "a", "an", "&"):
            words.pop()
    return " ".join(words) or "your podcast"


SHOWLIKE = re.compile(r"podcast|\bshow\b|radio|\btalk\b|cast\b|\bhour\b|\blive\b", re.I)


def _title_case(s):
    """Every word starts with a capital, so a subject line looks professional."""
    return " ".join(w[:1].upper() + w[1:] for w in s.split(" "))


def _phrases(lead, seed, n_links):
    """The pieces of the email that depend on the lead. Picks are fixed per lead so a re-preview shows what will go out."""
    pick = lambda key, opts: random.Random(f"{seed}:{key}").choice(opts)
    name = short_name(lead.get("name"))
    n = int(lead.get("clipCount") or 0) or n_links or 1
    show = (pick("show", [f"a new episode of {name}", f"a recent episode of {name}", f"an episode of {name}"]) if SHOWLIKE.search(name)
            else pick("show", [f"{name} on YouTube", f"the {name[4:]} channel on YouTube", f"some of the {name[4:]} videos on YouTube"]) if name.lower().startswith("the ")
            else pick("show", [f"your {name} videos on YouTube", f"your {name} channel on YouTube", f"a few of your {name} videos on YouTube"]))
    if n >= 3:
        clips = pick("clips", ["three short video clips", "a few short video clips"]) if n == 3 else "a few short video clips"
    elif n == 2:
        clips = pick("clips", ["two short video clips", "a couple of short video clips"])
    else:
        clips = "a short video clip"
    if n >= 2:
        done = pick("done", ["They're already done and they're yours, no charge and no strings attached.",
                             "They're finished and they're yours, free with no strings attached.",
                             "They're already done, and they're yours with no charge and no strings attached."])
    else:
        done = pick("done", ["It's already done and it's yours, no charge and no strings attached.",
                             "It's finished and it's yours, free with no strings attached.",
                             "It's already done, and it's yours with no charge and no strings attached."])
    return {"@@SHOW@@": show, "@@CLIPS@@": clips, "@@DONE@@": done, "@@THEM@@": "them" if n >= 2 else "it"}


def render(template, lead, cfg, step=0, subject_for_reply=None):
    """(subject, body) for one lead. Spintax picks are fixed per lead, so a re-preview shows the same email that will go out."""
    seed = f"{lead.get('id')}:{step}"
    links = [x for x in (lead.get("clipLinks") or []) if x] or [x for x in [lead.get("clipLink") or lead.get("link")] if x]
    ph = _phrases(lead, seed, len(links))

    def fill(t):
        t = (t.replace("{show_ref}", "@@SHOW@@").replace("{clips}", "@@CLIPS@@").replace("{done_line}", "@@DONE@@").replace("{them_it}", "@@THEM@@"))
        t = _prose(spin(t, seed))
        for k, v in ph.items():
            t = t.replace(k, v)
        return (t.replace("{niche}", str(lead.get("niche") or "your").replace("-", " "))
                .replace("{name}", short_name(lead.get("name")))
                .replace("{episode}", str(lead.get("epTitle") or "your recent episode"))
                .replace("{they_are}", "It is" if len(links) < 2 else "They are")
                .replace("{clip_link}", "\n".join(links))
                .replace("{topic}", _prose(str(lead.get("personal") or "")) or "your recent episode")
                .replace("{personal_line}", _prose(str(lead.get("personal") or "")))
                .replace("{sender}", str(cfg.get("sender_name") or "")))
    if step == 0 and (lead.get("body_override") or "").strip():
        subject = (lead.get("subject_override") or "").strip() or _title_case(fill(template.get("subject") or DEFAULT_SUBJECT))
        body = lead["body_override"].strip()
    elif step == 0:
        subject, body = _title_case(fill(template.get("subject") or DEFAULT_SUBJECT)), fill(template.get("body") or DEFAULT_BODY)
    else:
        days, text = FOLLOWUPS[min(step, len(FOLLOWUPS)) - 1]
        subject = "Re: " + (subject_for_reply or "your episode clip")
        body = fill(template.get(f"followup{step}") or text)
    footer = f"\n\n{cfg.get('postal_address', '')}\nNot interested? Just reply \"no thanks\" and I won't email you again."
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
def first_mail_for(log, to):
    return next((e for e in reversed(log) if e.get("to", "").lower() == to and e.get("step", 0) == 0 and e.get("status") == "sent"), None)


def plan(leads, template, mode="preview", limit=20, ignore_window=False, step=0):
    """Decides, for each lead in order, what would happen. No sending. Yields dicts (status: ready/skip)."""
    cfg, log = load_config(), read_log()
    used, recent = {}, {e["to"].lower() for e in sent_entries(log) if e.get("ts", 0) > time.time() - 90 * 86400 and e.get("step", 0) == step}
    d_ts, r_ts = {}, {}
    for e in log:
        k = e.get("to", "").lower()
        if e.get("status") == "drafted":
            d_ts[k] = max(d_ts.get(k, 0), e.get("ts", 0))
        elif e.get("status") == "draft_removed":
            r_ts[k] = max(r_ts.get(k, 0), e.get("ts", 0))
    drafted = {k for k, t in d_ts.items() if t > time.time() - 14 * 86400 and t > r_ts.get(k, 0)}
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
        if mode == "drafts" and step == 0 and to in drafted:
            yield {**base, "status": "skip", "why": "already saved as a draft"}
            continue
        provider = mx_provider(to.split("@", 1)[1]) if step == 0 else ((first_mail_for(log, to) or {}).get("provider") or "unknown")
        if step == 0 and provider in (template.get("skip_providers") if "skip_providers" in template else cfg.get("skip_providers", ["microsoft"])):
            yield {**base, "status": "skip", "why": f"mailbox is hosted by {provider.title()} (skipped for now)"}
            continue
        if step == 0 and not (ld.get("clipReady") or ld.get("clipLink") or ld.get("link")):
            yield {**base, "status": "skip", "why": "no clip prepared yet (prepare the clip first)"}
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
        variant = first_mail.get("variant", "A") if first_mail else "A"
        tpl_used = template
        if step == 0:
            variant, vs, vb = pick_variant(template, ld.get("id"))
            tpl_used = {**template, "subject": vs, "body": vb}
        subject, body = render(tpl_used, ld, cfg, step, ld.get("subject"))
        if acct:
            used[acct["email"]] = used.get(acct["email"], 0) + 1
        n += 1
        yield {**base, "status": "ready", "from": acct["email"] if acct else "(no inbox set up yet)", "subject": subject, "body": body,
               "in_reply_to": (first_mail or {}).get("message_id"), "variant": variant, "provider": provider}


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
            sleep(random.uniform(float(cfg.get("min_delay_seconds", 60)), float(cfg.get("max_delay_seconds", 90))))
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
                 "message_id": msg["Message-ID"], "status": status, "step": item["step"], "body": str(item.get("body") or "")[:4000],
                 "variant": item.get("variant"), "provider": item.get("provider")}
        append_log(entry)
        results.append({**item, "status": status, "message_id": msg["Message-ID"]})
        log_fn(f"{status} {item['to']} via {item['from']}")
    if mode == "send":
        try:
            delete_drafts([r["to"] for r in results if r.get("status") == "sent"], log_fn=lambda m: None)
        except Exception:
            pass
    return results


# ----------------------------------------------------------------------------------------- replies / opt outs
def _reply_text(raw):
    """(plain text without quoted earlier messages, Message-ID, Subject) from raw message bytes."""
    import email as _email
    msg = _email.message_from_bytes(raw or b"")
    text = ""
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_type() == "text/plain" and not part.get_filename():
            try:
                text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
            except Exception:
                text = ""
            if text:
                break
    keep = []
    for ln in text.splitlines():
        if ln.lstrip().startswith(">") or re.match(r"\s*On .{5,120}wrote:\s*$", ln) or re.match(r"\s*-{2,}\s*Original Message", ln, re.I):
            break
        keep.append(ln)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip(), (msg.get("Message-ID") or "").strip(), str(msg.get("Subject") or "").strip()


def check_replies(sent, log_fn=print):
    """sent: [{id, email, since_ts}]. Looks in each sending inbox for a reply from that address. Returns
    {found: [{id, email, kind: 'replied'|'optout', snippet}], errors: [...]} and adds opt-outs to the suppression list."""
    cfg, found, errors = load_config(), [], []
    by_acct = {}
    for e in sent_entries():
        by_acct.setdefault(e.get("from"), set()).add(e.get("to", "").lower())
    # Replies go to cfg["reply_to"]; if that inbox's login is saved as cfg["reply_account"], scan it for every prospect we emailed.
    all_sent_to = set().union(*by_acct.values()) if by_acct else set()
    inboxes = [(a, [s for s in sent if s["email"].lower() in by_acct.get(a["email"], set())]) for a in cfg.get("accounts", [])]
    ra = cfg.get("reply_account")
    if ra and ra.get("password"):
        inboxes.append(({**ra, "smtp_host": ra.get("imap_host", "")}, [s for s in sent if s["email"].lower() in all_sent_to]))
    seen_ids = set()
    for acct, wanted in inboxes:
        wanted = [s for s in wanted if s["id"] not in seen_ids]
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
                typ, raw = imap.fetch(ids[-1], "(BODY.PEEK[]<0.30000>)")
                text, msgid, rsubj = _reply_text(raw[0][1] if raw and raw[0] else b"")
                kind = "optout" if OPT_OUT.search(text) else "replied"
                if kind == "optout":
                    suppress(s["email"], "asked to stop")
                seen_ids.add(s["id"])
                if not any(e.get("to", "").lower() == s["email"].lower() and e.get("status") in ("replied", "optout") for e in read_log()):
                    fm = first_mail_for(read_log(), s["email"].lower()) or {}
                    append_log({"ts": time.time(), "id": s["id"], "to": s["email"].lower(), "status": kind, "step": 0,
                                "variant": fm.get("variant"), "provider": fm.get("provider")})
                found.append({"id": s["id"], "email": s["email"], "kind": kind, "snippet": re.sub(r"\s+", " ", text)[:160], "text": text[:1200],
                              "msgid": msgid, "subject": rsubj, "slug": s.get("slug"), "name": s.get("name")})
                log_fn(f"{kind}: {s['email']}")
            imap.logout()
        except Exception as e:
            errors.append(f"{acct['email']}: {str(e)[:120]}")
            log_fn(f"could not check {acct['email']}: {str(e)[:120]}")
    return {"found": found, "errors": errors}


def check_bounces(log_fn=print):
    """Looks in each sending inbox for delivery-failure notices and logs a 'bounced' entry for every address we emailed that failed.
    Returns {bounced: [addresses], errors: [...]}."""
    cfg, errors, bounced = load_config(), [], []
    log = read_log()
    sent_to = {e["to"].lower(): e for e in log if e.get("status") == "sent" and e.get("to")}
    already = {e["to"].lower() for e in log if e.get("status") == "bounced"}
    for acct in cfg.get("accounts", []):
        mine = {a for a, e in sent_to.items() if e.get("from") == acct["email"] and a not in already}
        if not mine:
            continue
        try:
            imap = imaplib.IMAP4_SSL(acct.get("imap_host") or acct["smtp_host"].replace("smtp.", "imap."))
            imap.login(acct.get("username") or acct["email"], acct["password"])
            imap.select("INBOX", readonly=True)
            since = (datetime.now() - timedelta(days=30)).strftime("%d-%b-%Y")
            typ, data = imap.search(None, f'(OR FROM "mailer-daemon" FROM "postmaster" SINCE {since})')
            for num in (data[0].split() if typ == "OK" and data and data[0] else [])[-200:]:
                raw = imap.fetch(num, "(BODY.PEEK[TEXT]<0.4000>)")[1]
                text = (raw[0][1].decode("utf-8", "ignore") if raw and raw[0] else "").lower()
                for addr in list(mine):
                    if addr in text:
                        fm = sent_to[addr]
                        append_log({"ts": time.time(), "id": fm.get("id"), "to": addr, "status": "bounced", "step": 0,
                                    "variant": fm.get("variant"), "provider": fm.get("provider")})
                        bounced.append(addr)
                        mine.discard(addr)
                        log_fn(f"bounced: {addr}")
            imap.logout()
        except Exception as e:
            errors.append(f"{acct['email']}: {str(e)[:120]}")
    return {"bounced": bounced, "errors": errors}


def delete_drafts(addresses, log_fn=print):
    """Removes the drafts THIS tool saved for these recipients (found by the Message-ID in the log) so they can be written again.
    Nothing else in the Drafts folder is touched. Returns the addresses whose draft was removed."""
    cfg, log = load_config(), read_log()
    want = {a.lower() for a in addresses}
    mine = {}
    for e in log:
        if e.get("status") == "drafted" and e.get("to", "").lower() in want and e.get("message_id"):
            mine.setdefault(e["from"], {})[e["message_id"]] = e["to"].lower()
    removed = set()
    for acct in cfg.get("accounts", []):
        ids = mine.get(acct["email"])
        if not ids:
            continue
        try:
            imap = imaplib.IMAP4_SSL(acct.get("imap_host") or acct["smtp_host"].replace("smtp.", "imap."))
            imap.login(acct.get("username") or acct["email"], acct["password"])
            imap.select("Drafts")
            for mid, to in ids.items():
                typ, data = imap.search(None, "HEADER", "Message-ID", mid)
                for num in (data[0].split() if typ == "OK" and data and data[0] else []):
                    imap.store(num, "+FLAGS", "\\Deleted")
                    removed.add(to)
            imap.expunge()
            imap.logout()
        except Exception as e:
            log_fn(f"could not clean drafts in {acct['email']}: {str(e)[:100]}")
    for to in removed:
        append_log({"ts": time.time(), "to": to, "status": "draft_removed", "mids": sorted(m for a in mine.values() for m, t in a.items() if t == to)})
        log_fn(f"removed old draft for {to}")
    return sorted(removed)


# ----------------------------------------------------------------------------------------- the unibox
def _body_text(msg):
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_type() == "text/plain" and not part.get_filename():
            try:
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
            except Exception:
                return ""
    return ""


def _open(acct, folder="Drafts", readonly=True):
    imap = imaplib.IMAP4_SSL(acct.get("imap_host") or acct["smtp_host"].replace("smtp.", "imap."))
    imap.login(acct.get("username") or acct["email"], acct["password"])
    imap.select(f'"{folder}"' if " " in folder or "[" in folder else folder, readonly=readonly)
    return imap


def pending_drafts():
    """Drafts this tool saved that are still waiting: {message_id: {kind, to, from, ts, step}}. First emails and auto replies."""
    log = read_log()
    gone = set()
    for e in log:
        if e.get("status") == "draft_removed":
            gone.update(e.get("mids") or [])
    out = {}
    for e in log:
        if e.get("status") in ("drafted", "auto_drafted") and e.get("message_id") and e["message_id"] not in gone:
            out[e["message_id"]] = {"kind": "reply" if e["status"] == "auto_drafted" else "first", "to": e.get("to", "").lower(),
                                    "from": e.get("from"), "ts": e.get("ts"), "id": e.get("id")}
    # a first email that was later really sent is no longer a draft
    sent_ts = {}
    for e in log:
        if e.get("status") == "sent" and e.get("step", 0) == 0:
            sent_ts[e.get("to", "").lower()] = max(sent_ts.get(e.get("to", "").lower(), 0), e.get("ts", 0))
    return {m: d for m, d in out.items() if not (d["kind"] == "first" and sent_ts.get(d["to"], 0) > d["ts"])}


def list_drafts(log_fn=print):
    """The saved drafts with their current text, read live from each sending inbox's Drafts folder (so edits made in webmail show up)."""
    cfg, pend = load_config(), pending_drafts()
    by_acct = {}
    for mid, d in pend.items():
        by_acct.setdefault(d["from"], {})[mid] = d
    items, errors = [], []
    for acct in cfg.get("accounts", []):
        mids = by_acct.get(acct["email"])
        if not mids:
            continue
        try:
            imap = _open(acct)
            for mid, d in mids.items():
                typ, data = imap.search(None, "HEADER", "Message-ID", mid)
                nums = data[0].split() if typ == "OK" and data and data[0] else []
                if not nums:
                    continue  # deleted in webmail
                raw = imap.fetch(nums[-1], "(BODY.PEEK[])")[1][0][1]
                m = email.message_from_bytes(raw)
                items.append({**d, "mid": mid, "inbox": acct["email"], "subject": str(m.get("Subject") or ""), "body": _body_text(m).strip(),
                              "reply_to": str(m.get("Reply-To") or ""), "date": str(m.get("Date") or "")})
            imap.logout()
        except Exception as e:
            errors.append(f"{acct['email']}: {str(e)[:100]}")
            log_fn(f"could not read drafts in {acct['email']}: {str(e)[:100]}")
    items.sort(key=lambda x: (x["kind"] != "reply", x.get("ts") or 0))
    return {"drafts": items, "errors": errors}


def _find_draft(mid):
    d = pending_drafts().get(mid)
    acct = next((a for a in load_config().get("accounts", []) if d and a["email"] == d["from"]), None)
    return d, acct


def update_draft(mid, subject, body, log_fn=print):
    """Replaces a saved draft's text. The old one is removed, a new one is saved, and the log is updated so sending uses the new text."""
    d, acct = _find_draft(mid)
    if not d or not acct:
        raise RuntimeError("that draft is no longer waiting")
    cfg = load_config()
    msg = compose(acct, cfg, d["to"], subject, body, None)
    imap = _open(acct, readonly=True)
    typ, data = imap.search(None, "HEADER", "Message-ID", mid)
    nums = data[0].split() if typ == "OK" and data and data[0] else []
    if nums:
        old = email.message_from_bytes(imap.fetch(nums[-1], "(BODY.PEEK[HEADER])")[1][0][1])
        for h in ("In-Reply-To", "References"):
            if old.get(h):
                msg[h] = old[h]
    imap.logout()
    save_draft(acct, msg)
    _remove_mid(acct, mid, d["to"])
    append_log({"ts": time.time(), "id": d.get("id"), "to": d["to"], "from": acct["email"], "status": "auto_drafted" if d["kind"] == "reply" else "drafted",
                "step": 0, "subject": subject, "message_id": msg["Message-ID"]})
    return msg["Message-ID"]


def _remove_mid(acct, mid, to):
    try:
        imap = _open(acct, readonly=False)
        typ, data = imap.search(None, "HEADER", "Message-ID", mid)
        for num in (data[0].split() if typ == "OK" and data and data[0] else []):
            imap.store(num, "+FLAGS", "\\Deleted")
        imap.expunge()
        imap.logout()
    finally:
        append_log({"ts": time.time(), "to": to, "status": "draft_removed", "mids": [mid]})


def discard_draft(mid):
    d, acct = _find_draft(mid)
    if not d or not acct:
        return False
    _remove_mid(acct, mid, d["to"])
    return True


def send_saved_reply(mid):
    """Sends an auto reply draft exactly as saved, then removes the draft. First emails are sent by the normal drip, not here."""
    d, acct = _find_draft(mid)
    if not d or not acct or d["kind"] != "reply":
        raise RuntimeError("that is not a reply draft that is waiting")
    imap = _open(acct)
    typ, data = imap.search(None, "HEADER", "Message-ID", mid)
    nums = data[0].split() if typ == "OK" and data and data[0] else []
    if not nums:
        raise RuntimeError("the draft is not in the Drafts folder any more")
    msg = email.message_from_bytes(imap.fetch(nums[-1], "(BODY.PEEK[])")[1][0][1])
    imap.logout()
    out = EmailMessage()
    for k, v in msg.items():
        if k.lower() not in ("content-type", "content-transfer-encoding", "mime-version", "date"):
            out[k] = v
    out["Date"] = email.utils.formatdate(localtime=True)
    out.set_content(_body_text(msg))
    send_message(acct, out)
    _remove_mid(acct, mid, d["to"])
    append_log({"ts": time.time(), "id": d.get("id"), "to": d["to"], "from": acct["email"], "status": "auto_replied", "step": 0, "subject": str(msg.get("Subject") or ""), "message_id": out["Message-ID"]})
    return True


def list_replies(days=21, limit=80):
    """Recent mail that prospects sent back, across the reply inbox and every sending inbox, newest first."""
    cfg, log = load_config(), read_log()
    prospects = {e.get("to", "").lower() for e in log if e.get("status") in ("sent", "drafted") and e.get("to")}
    boxes = [dict(a, _label=a["email"]) for a in cfg.get("accounts", [])]
    ra = cfg.get("reply_account")
    if ra and ra.get("password"):
        boxes.insert(0, dict(ra, smtp_host=ra.get("imap_host", ""), _label=ra["email"] + " (reply inbox)"))
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    items, errors, seen = [], [], set()
    for acct in boxes:
        try:
            imap = _open(acct, "INBOX")
            typ, data = imap.search(None, f"(SINCE {since})")
            nums = data[0].split() if typ == "OK" and data and data[0] else []
            for num in nums[-150:]:
                raw = imap.fetch(num, "(BODY.PEEK[]<0.20000>)")[1][0][1]
                m = email.message_from_bytes(raw)
                frm = email.utils.parseaddr(str(m.get("From") or ""))[1].lower()
                if not frm or frm not in prospects or frm in {a["email"].lower() for a in cfg.get("accounts", [])}:
                    continue
                mid = str(m.get("Message-ID") or "").strip()
                if mid in seen:
                    continue
                seen.add(mid)
                text, _, _ = _reply_text(raw)
                items.append({"mid": mid, "from": frm, "inbox": acct["_label"], "subject": str(m.get("Subject") or ""), "date": str(m.get("Date") or ""),
                              "ts": email.utils.mktime_tz(email.utils.parsedate_tz(str(m.get("Date")))) if m.get("Date") and email.utils.parsedate_tz(str(m.get("Date"))) else 0,
                              "text": (text or _body_text(m)).strip()[:1500]})
            imap.logout()
        except Exception as e:
            errors.append(f"{acct['_label']}: {str(e)[:100]}")
    items.sort(key=lambda x: -x["ts"])
    return {"replies": items[:limit], "errors": errors}
