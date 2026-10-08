#!/usr/bin/env python3
"""
Checks your sending setup BEFORE you send anything. Reads only; sends nothing unless you add --send-test.

    python3 tools/check_email_setup.py
    python3 tools/check_email_setup.py --send-test you@your-personal-address.com   # one real test email from each inbox, to YOU
    python3 tools/check_email_setup.py --only world --send-test you@gmail.com     # limit everything to inboxes whose address contains "world"
    python3 tools/check_email_setup.py --read-results you@gmail.com               # then: did each test land in inbox or spam, and did SPF/DKIM/DMARC pass?

For every inbox it checks: the domain's SPF, DKIM and DMARC records (what makes mail land in the inbox instead of spam), that the domain can receive mail
(so replies reach you), and that the SMTP (sending) and IMAP (reading replies) logins work. Every problem comes with the exact fix.
"""
import email as emaillib
import getpass
import imaplib
import re
import json
import os
import smtplib
import subprocess
import sys
from pathlib import Path

HERE = Path(os.getenv("COLD_EMAIL_HOME") or Path(__file__).resolve().parent)
sys.path.insert(0, str(Path(__file__).resolve().parent))
GOOD, WARN, BAD = "  ok   ", "  WARN ", "  FIX  "


def txt(name):
    out = subprocess.run(["nslookup", "-type=txt", name], capture_output=True, text=True, timeout=15).stdout
    return out.replace('"', "").lower()


def mx_ok(domain):
    return "mail exchanger" in subprocess.run(["nslookup", "-type=mx", domain], capture_output=True, text=True, timeout=15).stdout.lower()


def dns_checks(acct):
    domain = acct["email"].split("@")[1].lower()
    host = (acct.get("smtp_host") or "").lower()
    google = "gmail" in host or "google" in host
    # (name, text the SPF record must contain, the record to add). Zoho's include depends on your Zoho region (zoho.com, zoho.eu, zoho.in).
    provider = (("Google", "_spf.google.com", "v=spf1 include:_spf.google.com ~all") if google else
                ("Zoho", "zoho.", "v=spf1 include:zoho.com ~all") if "zoho" in host else
                ("Microsoft", "spf.protection.outlook.com", "v=spf1 include:spf.protection.outlook.com ~all") if "office365" in host or "outlook" in host else
                ("Namecheap", "spf.privateemail.com", "v=spf1 include:spf.privateemail.com ~all") if "privateemail" in host else None)
    out = []
    spf = txt(domain)
    if "v=spf1" in spf:
        out.append((GOOD, f"SPF record found for {domain}"))
        if provider and provider[1] not in spf:
            out.append((WARN, f"SPF doesn't mention {provider[0]}. Set the TXT record on {domain} to: {provider[2]}"))
    else:
        out.append((BAD, f"No SPF record on {domain}. Add a TXT record (host @): {provider[2]}" if provider else f"No SPF record on {domain}. Add the TXT record your mail provider lists for SPF."))
    if google:
        dkim = txt(f"google._domainkey.{domain}")
        out.append((GOOD, "DKIM record found") if "v=dkim1" in dkim else
                   (BAD, f"No DKIM record. In Google Admin: Apps > Google Workspace > Gmail > Authenticate email, generate the key, add the TXT record it shows (host google._domainkey), then press Start authentication."))
    elif "privateemail" in host:
        hit = next((sel for sel in ("default", "privateemail", "mail", "dkim") if "v=dkim1" in txt(f"{sel}._domainkey.{domain}")), None)
        out.append((GOOD, f"DKIM record found (selector {hit})") if hit else
                   (WARN, "No DKIM record found at the usual names. In the Private Email dashboard switch DKIM on and add the TXT record it shows (if the domain uses Namecheap DNS it may add it for you). It can take a few hours to appear."))
    else:
        out.append((WARN, "DKIM isn't auto-checked for this provider. In its admin panel, switch DKIM on and add the TXT record it shows."))
    dmarc = txt(f"_dmarc.{domain}")
    out.append((GOOD, "DMARC record found") if "v=dmarc1" in dmarc else
               (BAD, f"No DMARC record. Add a TXT record, host _dmarc: v=DMARC1; p=none; rua=mailto:{acct['email']}"))
    out.append((GOOD, f"{domain} can receive mail (replies will reach you)") if mx_ok(domain) else
               (BAD, f"{domain} has no mail server (MX) records, so replies would bounce. Add your provider's MX records."))
    return out


def login_checks(acct):
    out = []
    try:
        port = int(acct.get("smtp_port", 587))
        s = smtplib.SMTP_SSL(acct["smtp_host"], port, timeout=20) if port == 465 else smtplib.SMTP(acct["smtp_host"], port, timeout=20)
        if port != 465 and acct.get("tls", True):
            s.starttls()
        if acct.get("password"):
            s.login(acct.get("username") or acct["email"], acct["password"])
        s.quit()
        out.append((GOOD, "sending login works (SMTP)"))
    except Exception as e:
        out.append((BAD, f"sending login failed: {str(e)[:110]}. Use an APP PASSWORD (Google: turn on 2-Step Verification, then myaccount.google.com/apppasswords)."))
    try:
        host = acct.get("imap_host") or acct["smtp_host"].replace("smtp.", "imap.")
        i = imaplib.IMAP4_SSL(host, timeout=20)
        i.login(acct.get("username") or acct["email"], acct["password"])
        i.logout()
        out.append((GOOD, "reading login works (IMAP): replies and drafts will work"))
    except Exception as e:
        out.append((BAD, f"reading login failed: {str(e)[:110]}. Reply detection and Gmail drafts need IMAP (Gmail: Settings > Forwarding and POP/IMAP > Enable IMAP)."))
    return out


IMAP_HOSTS = {"gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com", "outlook.com": "outlook.office365.com",
              "hotmail.com": "outlook.office365.com", "live.com": "outlook.office365.com", "yahoo.com": "imap.mail.yahoo.com",
              "icloud.com": "imap.mail.me.com"}
SPAM_FOLDERS = ("[Gmail]/Spam", "Junk", "Junk Email", "Spam", "Bulk Mail")
TEST_SUBJECT = "Test from your outreach setup"


def read_results(to, accounts):
    """Log in to the inbox the tests were sent TO, find each test and report folder + SPF/DKIM/DMARC as the receiver judged them."""
    host = IMAP_HOSTS.get(to.split("@")[1].lower()) or input(f"IMAP server for {to}: ").strip()
    pw = getpass.getpass(f"App password for {to} (hidden, used only for this check): ")
    found = {}
    try:
        im = imaplib.IMAP4_SSL(host, timeout=25)
        im.login(to, pw)
    except Exception as e:
        print(BAD + f"could not log in to {to}: {str(e)[:120]}")
        return 1
    for folder in ("INBOX",) + SPAM_FOLDERS:
        try:
            if im.select(f'"{folder}"', readonly=True)[0] != "OK":
                continue
            typ, data = im.search(None, "SUBJECT", f'"{TEST_SUBJECT}"')
            for num in (data[0].split() if typ == "OK" else [])[-40:]:
                raw = im.fetch(num, "(BODY.PEEK[HEADER])")[1][0][1]
                msg = emaillib.message_from_bytes(raw)
                sender = emaillib.utils.parseaddr(msg.get("From", ""))[1].lower()
                auth = " ".join(msg.get_all("Authentication-Results") or []).lower()
                found[sender] = (folder, auth)  # later (newer) messages overwrite earlier ones
        except Exception:
            continue
    im.logout()
    bad = 0
    print(f"\nWHAT {to} RECEIVED")
    for a in accounts:
        sender = a["email"].lower()
        if sender not in found:
            print(WARN + f"{sender}: no test email found (not delivered yet, or wrong folder). Wait a minute and run again.")
            continue
        folder, auth = found[sender]
        verdicts = {k: (re.search(rf"\b{k}=(\w+)", auth).group(1) if re.search(rf"\b{k}=(\w+)", auth) else "not reported") for k in ("spf", "dkim", "dmarc")}
        placed = "INBOX" if folder == "INBOX" else f"SPAM ({folder})"
        line = f"{sender}: landed in {placed}; SPF {verdicts['spf']}, DKIM {verdicts['dkim']}, DMARC {verdicts['dmarc']}"
        ok = folder == "INBOX" and all(v == "pass" for v in verdicts.values())
        print((GOOD if ok else BAD) + line)
        if not ok:
            bad += 1
            if verdicts["spf"] not in ("pass", "not reported"):
                print("         fix: SPF is wrong. Fix the TXT record on @ for that domain.")
            if verdicts["dkim"] not in ("pass", "not reported"):
                print("         fix: DKIM failed. Turn on DKIM in your mail provider's dashboard and add its TXT record.")
            if verdicts["dmarc"] not in ("pass", "not reported"):
                print("         fix: DMARC failed. Add the _dmarc TXT record and make sure SPF or DKIM aligns with the From domain.")
            if folder != "INBOX" and all(v == "pass" for v in verdicts.values()):
                print("         all checks passed but it still went to spam: that is the provider's shared IP/reputation, not your setup. If every inbox does this, this host is a poor fit for cold email.")
    return bad


def main():
    cfgfile = HERE / "email_accounts.json"
    if not cfgfile.exists():
        sys.exit("No tools/email_accounts.json yet. Run: python3 tools/setup_email.py")
    cfg = json.loads(cfgfile.read_text(encoding="utf-8"))
    bad = 0
    print("\nYOUR DETAILS")
    for label, val in (("name", cfg.get("sender_name")), ("postal address", cfg.get("postal_address"))):
        ok = bool((val or "").strip()) and val not in ("Your Name",) and "mailing address" not in val
        print((GOOD if ok else BAD) + (f"{label}: {val}" if ok else f"{label} is missing (cold email law requires both in every email). Run python3 tools/setup_email.py"))
        bad += 0 if ok else 1
    accounts = cfg.get("accounts") or []
    if "--only" in sys.argv:
        want = sys.argv[sys.argv.index("--only") + 1].lower()
        accounts = [a for a in accounts if want in a["email"].lower()]
        print(f"\n(--only {want}: checking {len(accounts)} inbox{'es' if len(accounts) != 1 else ''})")
        if not accounts:
            sys.exit(f"No inbox matches '{want}'. Inboxes: " + ", ".join(a["email"] for a in cfg.get("accounts") or []))
    if not accounts:
        print(BAD + "no inboxes. Run python3 tools/setup_email.py")
        bad += 1
    rt = (cfg.get("reply_to") or "").lower()
    if rt and rt.split("@")[-1] in ("gmail.com","googlemail.com","yahoo.com","outlook.com","hotmail.com","live.com","icloud.com","aol.com","proton.me","protonmail.com"):
        print(WARN + f"Reply-To is a free address ({rt}). Before real outreach, switch it to a mailbox on a domain you own (setup_email.py option 4): a Gmail Reply-To costs about 2.5 spam points.")
    risky = sorted({a["email"].split("@")[1].rsplit(".", 1)[-1].lower() for a in accounts} & {"online", "site", "space", "store", "world", "xyz", "top", "click", "club", "shop", "icu", "buzz", "monster", "cyou", "sbs", "quest", "rest", "fun", "work", "win", "bid", "vip", "live", "website", "tech", "cfd"})
    if risky:
        print(WARN + "Domain endings spam filters distrust: " + ", ".join("." + t for t in risky) + ". mail-tester scored these 6/10 (about 3.5 points lost to the ending alone). A .com ending avoids it.")
    domains = [a["email"].split("@")[1].lower() for a in accounts]
    if len(accounts) > 1 and len(set(domains)) == 1:
        print(WARN + "all inboxes share one domain. Spreading them over 2 or 3 domains protects you if one domain gets a bad reputation.")
    for a in accounts:
        print(f"\n{a['email']}")
        for mark, msg in dns_checks(a) + login_checks(a):
            print(mark + msg)
            bad += 1 if mark == BAD else 0
    to = sys.argv[sys.argv.index("--send-test") + 1] if "--send-test" in sys.argv else None
    if to:
        import cold_email
        print(f"\nSENDING ONE TEST EMAIL FROM EACH INBOX TO {to}")
        for a in accounts:
            try:
                cold_email.send_message(a, cold_email.compose(a, cfg, to, "Test from your outreach setup", "If you can read this, this inbox can send.\n\nCheck that it landed in your inbox, not spam.\n\n--\n" + cfg.get("sender_name", "")))
                print(GOOD + f"sent from {a['email']}")
            except Exception as e:
                print(BAD + f"{a['email']}: {str(e)[:120]}")
                bad += 1
    rr = sys.argv[sys.argv.index("--read-results") + 1] if "--read-results" in sys.argv else None
    if rr:
        bad += read_results(rr, accounts)
    print("\n" + ("All clear. You can preview, then try one inbox's drafts." if not bad else f"{bad} thing(s) to fix above, then run this again."))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
