# Setting up cold email (rotation across several inboxes)

Goal: 2 to 3 separate sending domains, 1 to 2 inboxes on each, protected by SPF, DKIM and DMARC. The engine then rotates
across them and keeps each inbox under a small daily cap that grows slowly.

## 1. Domains (about 20 minutes)
- Buy 2 or 3 NEW domains that are **not** your main brand domain (Namecheap, Porkbun or Cloudflare). A bad sending reputation then never touches your real site.
- Pick plain, honest names close to what you do (for example `trypodclips.com`). Do not imitate anyone else's brand. Google rejects domains with "gmail" in them.
- Point each domain's website to your real page (a simple redirect) so a recipient who checks you out finds you.

## 2. Inboxes (Google Workspace shown; Zoho Mail and Microsoft 365 also work in the wizard)
- Each new domain is added to Google Workspace as a **secondary domain**, and you create a real user (mailbox) on it, for example `emmanuel@trypodclips.com`. Every mailbox is billed per seat (check Google's current price).
- A "domain alias" is free but is NOT a separate inbox, so it does not give you real rotation. Use secondary domains with real users.
- Do not use your personal Gmail for cold email.

## 3. DNS records on each domain (the checker tells you exactly what is missing)
| Record | Host | Value |
|---|---|---|
| SPF (TXT) | `@` | `v=spf1 include:_spf.google.com ~all` |
| DKIM (TXT) | `google._domainkey` | the long value Google Admin shows under Apps > Google Workspace > Gmail > Authenticate email, then press Start authentication |
| DMARC (TXT) | `_dmarc` | `v=DMARC1; p=none; rua=mailto:you@thatdomain.com` |
| MX | `@` | the Google MX records Workspace shows during setup (so replies reach you) |

## 4. Let the app log in (per inbox)
1. Turn on **2-Step Verification** for that user (an authenticator app or phone prompt).
2. Create an **App password** at myaccount.google.com/apppasswords. Copy it.
3. In Google Admin, make sure **IMAP access** and **SMTP** are allowed for the user (needed to send, read replies and save drafts).

## 5. Tell the engine about them
```
python3 tools/setup_email.py          # your name, postal address, each inbox (passwords are typed hidden)
python3 tools/check_email_setup.py    # checks DNS records and both logins, tells you exactly what to fix
python3 tools/check_email_setup.py --send-test you@your-personal-address.com   # one real test email from each inbox to YOU
```
Open the test emails and check they landed in your inbox, not spam.

## 6. Ramp up slowly (the defaults already do this)
- Week 1: about 5 emails a day per inbox. Each day adds 3, up to 30. Stay low if anything lands in spam or bounces.
- With 4 inboxes that is roughly 20 a day at first, growing to about 120 a day after a couple of weeks.
- Stop and check if you see bounces or spam placement. Replies and opens help your reputation; ignored cold mail hurts it.
- Send only to podcasts that fit. Quality beats volume.

## 7. Turn it on in the CRM
Restart the helper (`python3 tools/local_runner.py`), open the **Email** tab, and use: 1 Find emails, 2 Prepare clips, 3 Preview, then
**Save as Gmail drafts** with the first inbox and read what it made before your first real send.
