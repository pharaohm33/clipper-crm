# Clipper CRM

**Web app (no install): https://pharaohm33.github.io/clipper-crm/** — runs in your browser, data saved locally (export a JSON backup from Settings). The Google Sheets version below has more power (Telegram bot integration, About-page social scraping).

A Google Sheets CRM + Apps Script for podcast clippers: find podcasts on YouTube, pull their Instagram/X/TikTok/link-in-bio (no email), DM a free sample clip, and track money per influencer toward a monthly goal.

**Nothing personal is stored in this repo.** Everyone enters their *own* YouTube API key in their *own* Sheet's `Settings` tab.

## Install (5 min)
1. New Google Sheet → Extensions → Apps Script → paste `ClipperCRM.gs` → Save.
2. Run `setupCRM` (approve permissions). Reload the Sheet.
3. `Settings` tab: add your YouTube Data API v3 key.

## Daily flow
Clipper CRM menu → Find podcasts → Build today's outreach list → clip the episode → DM → tick **Sent?** → log payments.

## Telegram coaching (optional)
The sheet includes `KPI Summary` and `Daily Outreach Log` tabs in the format used by the [AI Executive Coach bot](https://github.com/pharaohm33/productivity_bot). Connect this Sheet to that bot as your CRM and it coaches you from your live DM count, follow-ups and income. Don't use `/set_income`/`/set_expenses` — those cells are formulas.

MIT licensed.

## Auto-fill leads from Google AI Mode (optional)
`tools/google_ai_to_crm.py` opens Google AI Mode in Chrome, asks for podcasts per niche, reads the answer table
(including the hidden links) and adds new leads to your Sheet. The website merges them in when you open it.

```bash
pip install playwright requests
export CRM_SYNC_URL="https://script.google.com/macros/s/.../exec"   # your Apps Script web app
export CRM_SYNC_PASSWORD="..."                                      # your sync password
export YT_API_KEY="..."                                             # recommended: finds channels + episodes
python tools/google_ai_to_crm.py "real estate" "personal finance"   # add --dry-run to preview
```
If Google shows a "verify you're human" check, solve it yourself in the window; the script waits.
No Google login is needed (Google blocks sign-in inside automated browsers; the script works signed out).
Runs use a separate Chrome profile (`~/.clipper_chrome_profile`). Keep runs small (a few niches) to avoid checks.
Re-paste `ClipperCRM.gs` into Apps Script and redeploy (new version) to enable the append endpoint.

### One-click from the website
The **Run live and send to CRM** button on Find Podcasts starts the script for you. Browsers can't launch programs,
so run this small helper once and leave it open:
```bash
cp tools/.env.example tools/.env      # then fill in CRM_SYNC_URL, CRM_SYNC_PASSWORD, YT_API_KEY (git-ignored)
python3 tools/local_runner.py
```
It listens only on `127.0.0.1` and only accepts requests from this site. Your keys stay in `tools/.env`.

## Grab just a slice of a podcast video
```bash
tools/grab_sample.sh "https://www.youtube.com/watch?v=VIDEO_ID" 12:00 17:00
```
Downloads only that time range (default 10:00 to 15:00) into `~/Downloads/clip-samples`, so you can make a sample clip fast.
Needs ffmpeg and yt-dlp. If it says all attempts failed, run `brew install yt-dlp`.

## Send a slice to your local clipper app
With the helper running (`python3 tools/local_runner.py`), the header shows **Clipper: on / busy / off** (read from your clipper app at
`http://127.0.0.1:5001`, change with `CLIPPER_URL`). On the Today tab, **Send 5 min to clipper** downloads a slice of the lead's episode and
saves it as a new template in the clipper, in the parent folder "Podcast Outreach" (change with `SAMPLES_FOLDER`). The lead remembers the sample file and its folder; **Match existing samples** (Leads tab) links samples you already made to their leads, and **Show file** reveals it in Finder. It does not generate clips: change the rules in the clipper, then press Generate.
If the clipper is busy it waits (up to 15 minutes); if it is off, the file is kept and the helper tells you where it is.

### Template settings for outreach samples
Every template the helper creates starts with the clipper settings in `tools/outreach_settings.json` (captions on, High quality, auto silence cut
at 0.8s, quote on, reuse off, virality filter off, complete idea on, hook title on, DeepSeek on, and save all as drafts). Edit that file to change them.
To re-apply them to the templates already in the Podcast Outreach folder: `python3 tools/apply_outreach_settings.py` (add `--dry-run` to preview).

## Cold email system (find, clip, email)
The **Email** tab runs the whole chain for podcasts you haven't contacted:
1. **Find emails**: a podcast's public contact email, taken from its RSS feed, its YouTube description, or its own website. Never guessed.
2. **Prepare clips**: for each lead, the helper downloads a slice of their episode (skipping the intro), makes one clip with your template settings, and puts it on a Drive link anyone can open.
3. **Preview, Drafts or Send**: a short email with the link. Preview sends nothing.
4. **Follow-ups** (3 and 7 days, same inbox, same thread) and **Check replies** (anyone who says no is added to the do-not-contact list).

**Setup (once):** follow `tools/EMAIL_SETUP.md`. In short: `python3 tools/setup_email.py` (passwords typed hidden into your own terminal), then
`python3 tools/check_email_setup.py` (checks the domain records and logins), then `python3 tools/local_runner.py` and open the Email tab.

**Protecting your sending reputation:** use separate sending domains (not your main one) with SPF, DKIM and DMARC set up, several inboxes, and keep the
default slow ramp (5 a day, growing 3 a day, 30 max per inbox). The engine rotates inboxes, spaces sends randomly inside a 9 to 5 window,
and never emails the same address twice in 90 days.

**The law:** every email carries your real name, postal address and an opt-out line, and anyone who opts out is never emailed again (CAN-SPAM requires this).
If you email people in the EU, UK or Canada, those places have stricter rules for cold email. Check them first.
