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
