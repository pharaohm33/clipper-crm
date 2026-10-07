# Clipper CRM

A Google Sheets CRM + Apps Script for podcast clippers: find podcasts on YouTube, pull their Instagram/X/TikTok/link-in-bio (no email), DM a free sample clip, and track money per influencer toward a monthly goal. Includes a Telegram accountability coach powered by DeepSeek.

**Nothing personal is stored in this repo.** Everyone who uses it enters their *own* keys in their *own* Sheet's `Settings` tab (YouTube API key, Telegram bot token, DeepSeek key). Your keys never leave your Google account.

## Install (5 min)
1. New Google Sheet → Extensions → Apps Script.
2. Paste `ClipperCRM.gs` and add a second file `CoachBot.gs` with that code. Save.
3. Project Settings → set your time zone.
4. Run `setupCRM` (approve permissions). Reload the Sheet.
5. `Settings` tab: add your YouTube Data API v3 key, then Telegram bot token (from @BotFather) and DeepSeek key.
6. Menu **Clipper CRM → Start Telegram coach**, then send `/start` to your bot.

## Daily flow
Find podcasts → Build today's outreach list → clip the episode → DM → tick **Sent?** → log payments.

## Telegram commands
`/status` `/today` `/pay 150 Podcast Name` — or just chat. Reminder times are configurable in Settings.

MIT licensed.
