# Clipper CRM

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
