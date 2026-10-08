#!/usr/bin/env python3
"""
Guided setup for your sending inboxes. Run it in your own Terminal:

    python3 tools/setup_email.py

It asks for your name, postal address and each inbox, and writes tools/email_accounts.json (readable only by you, never committed).
Passwords are typed hidden into YOUR terminal: never paste them into a chat or an issue. Use an APP PASSWORD, not the account password.
Run it again any time to add or remove an inbox.
"""
import getpass
import json
import os
import stat
from pathlib import Path

HERE = Path(os.getenv("COLD_EMAIL_HOME") or Path(__file__).resolve().parent)
CONFIG = HERE / "email_accounts.json"
DEFAULTS = {"sender_name": "", "postal_address": "", "reply_to": "", "send_window": {"start_hour": 9, "end_hour": 17},
            "min_delay_seconds": 90, "max_delay_seconds": 240, "warmup": {"start": 5, "add_per_day": 3, "max": 30}, "accounts": []}
PROVIDERS = {"1": ("Google Workspace or Gmail", "smtp.gmail.com", 587, "imap.gmail.com"),
             "2": ("Zoho Mail", "smtp.zoho.com", 587, "imap.zoho.com"),
             "3": ("Microsoft 365 / Outlook", "smtp.office365.com", 587, "outlook.office365.com"),
             "4": ("Something else (I know the server names)", "", 587, "")}


def ask(prompt, default=""):
    shown = f" [{default}]" if default else ""
    return (input(f"{prompt}{shown}: ").strip() or default)


def load():
    if CONFIG.exists():
        return {**DEFAULTS, **json.loads(CONFIG.read_text(encoding="utf-8"))}
    return json.loads(json.dumps(DEFAULTS))


def save(cfg):
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG, stat.S_IRUSR | stat.S_IWUSR)  # only you can read it
    except OSError:
        pass


def show(cfg):
    print(f"\n  Name: {cfg['sender_name'] or '(not set)'}\n  Postal address: {cfg['postal_address'] or '(not set)'}")
    if not cfg["accounts"]:
        print("  Inboxes: none yet")
    for i, a in enumerate(cfg["accounts"], 1):
        print(f"  Inbox {i}: {a['email']}  ({a['smtp_host']})  password: {'saved (hidden)' if a.get('password') else 'MISSING'}  daily limit {a.get('daily_limit', 20)}")
    print()


def add_inbox(cfg):
    print("\nWhich kind of inbox?")
    for k, (name, *_rest) in PROVIDERS.items():
        print(f"  {k}) {name}")
    kind = PROVIDERS.get(ask("Pick 1-4", "1"), PROVIDERS["1"])
    email = ask("Inbox email address").lower()
    if "@" not in email:
        print("  That doesn't look like an email address. Skipped.")
        return
    if any(a["email"].lower() == email for a in cfg["accounts"]):
        print("  That inbox is already added. Remove it first to change it.")
        return
    smtp, imap = kind[1] or ask("SMTP server (for sending)"), kind[3] or ask("IMAP server (for reading replies)")
    print("  Now the APP PASSWORD (typing is hidden; paste it with Cmd+V and press Enter).")
    pw = getpass.getpass("  App password: ").replace(" ", "").strip()
    limit = int(ask("  Most emails this inbox may send per day (the slow ramp stays under this)", "20") or 20)
    cfg["accounts"].append({"email": email, "smtp_host": smtp, "smtp_port": kind[2], "tls": True, "imap_host": imap,
                            "username": email, "password": pw, "daily_limit": limit})
    print(f"  Added {email}.")


def main():
    cfg = load()
    print(__doc__.split("\n\n")[0])
    if not cfg["sender_name"]:
        cfg["sender_name"] = ask("Your name (shown as the sender)")
    if not cfg["postal_address"]:
        cfg["postal_address"] = ask("Your real mailing address (cold email law requires it in every email)")
    while True:
        show(cfg)
        print("  1) Add an inbox   2) Remove an inbox   3) Change name or address   4) Save and finish")
        choice = ask("Pick 1-4", "4")
        if choice == "1":
            add_inbox(cfg)
        elif choice == "2" and cfg["accounts"]:
            n = int(ask("Remove which inbox number") or 0)
            if 1 <= n <= len(cfg["accounts"]):
                print(f"  Removed {cfg['accounts'].pop(n - 1)['email']}.")
        elif choice == "3":
            cfg["sender_name"] = ask("Your name", cfg["sender_name"])
            cfg["postal_address"] = ask("Mailing address", cfg["postal_address"])
        elif choice == "4":
            break
    save(cfg)
    print(f"\nSaved to {CONFIG} (only you can read it).")
    problems = []
    if not cfg["accounts"]:
        problems.append("no inboxes yet")
    if not cfg["sender_name"] or not cfg["postal_address"]:
        problems.append("name and postal address are both required")
    print("Next: python3 tools/check_email_setup.py" if not problems else "Still needed: " + "; ".join(problems))


if __name__ == "__main__":
    main()
