#!/usr/bin/env python3
"""
Checks your sending setup BEFORE you send anything. Reads only; sends nothing unless you add --send-test.

    python3 tools/check_email_setup.py
    python3 tools/check_email_setup.py --send-test you@your-personal-address.com   # one real test email from each inbox, to YOU

For every inbox it checks: the domain's SPF, DKIM and DMARC records (what makes mail land in the inbox instead of spam), that the domain can receive mail
(so replies reach you), and that the SMTP (sending) and IMAP (reading replies) logins work. Every problem comes with the exact fix.
"""
import imaplib
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
                ("Microsoft", "spf.protection.outlook.com", "v=spf1 include:spf.protection.outlook.com ~all") if "office365" in host or "outlook" in host else None)
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
    if not accounts:
        print(BAD + "no inboxes. Run python3 tools/setup_email.py")
        bad += 1
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
    print("\n" + ("All clear. You can preview, then try one inbox's drafts." if not bad else f"{bad} thing(s) to fix above, then run this again."))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
