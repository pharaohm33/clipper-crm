# Quick start

Everything runs on your Mac. The CRM page is the control panel, a small helper on your computer does the work (Google AI searches, email, clips), and the clipper app makes the clips.

CRM: https://pharaohm33.github.io/clipper-crm/

## Start and stop

Start everything (helper, clipper app, the Google AI Chrome window):

```bash
~/clipper-crm/tools/start_outreach.command
```

Stop everything:

```bash
~/clipper-crm/tools/stop_outreach.command
```

Run these from anywhere. The scripts live in `~/clipper-crm/tools/`, so a bare `stop_outreach.command` will not be found.

Restart the helper after any update to the `tools/` folder so it loads the new code (stop, then start).

## A normal day

1. Start everything, open the CRM, and keep that **one** tab open. Autopilot only runs while its tab is open, and one tab at a time.
2. **Email tab:** turn Autopilot on. It finds leads, finds emails, checks each lead is a good fit, makes clips, writes the emails and saves them as **drafts**. Nothing is sent in "save to drafts" mode.
3. **Unibox tab:** read the drafts, edit if you like, press **Approve** on the ones you want. Each draft also shows what the reply will say if they answer yes, including their Google Sheet link.
4. Sending, either way:
   - Press **Drip-send the approved**: sends one every 60 to 90 seconds, rotating inboxes, inside each inbox's daily limit.
   - Or tick **Auto-send approved drafts during sending hours** (9 to 5 Arizona time): approved drafts go out by themselves while autopilot is on.
5. When someone replies yes, the reply with the sheet link and your number is saved as a draft for you to approve. Replies show in the Unibox.
6. **Calls tab:** follow up by phone on the leads who have a number.

## What autopilot does each round

1. Records anything already sent.
2. Searches Google AI for more leads (your custom searches first, then each niche state by state).
3. Finds emails (their website, YouTube About page and podcast feed, then Google AI as a last resort). **No email means the lead is skipped**, not waited on.
4. Checks every address is real before any clip is made.
5. Checks each lead is a good fit (Gemini, then Google AI in Chrome when the Gemini quota runs out).
6. Makes up to 3 clips per lead and a topic line from the episode.
7. Writes the emails and saves them as drafts (or sends them, if you chose that mode).
8. Checks replies.
9. Optional last step: finds phone numbers for follow-up calls. It never holds up drafts.

The review limit ("Keep at most") counts only drafts still waiting for you to approve. Approved drafts waiting to send do not block new work.

## Find Podcasts tab

- **Custom Google AI searches:** type any search (for example "luxury car dealer podcasts") and an optional angle. Autopilot runs these first. The table below it shows everything autopilot searches, when each last ran, and how many leads it kept.
- Niches are searched state by state, so there is no waiting between rounds. A niche and state pair repeats after 30 days.

## Calls tab

- Leads with a public phone number, replied or emailed leads first.
- Buttons: called no answer, left voicemail, sent a text, spoke, interested, call back later, not interested, wrong number, do not call. Every press is logged with the time, and each log entry has **Remove** to undo a mistake (it also undoes the status change).
- Each lead has links to their YouTube channel, the episode clipped, the clip links, and the **client folder (Google Sheet)**. The sheet link is saved on the lead automatically once its clips exist.
- **Emails and replies** shows what you sent them and what they answered. **Open in Unibox** jumps to it.
- The Google AI phone search prompt and your call, voicemail and text scripts are editable at the bottom of the tab.
- Numbers come from public pages only. Check the National Do Not Call list and your state's rules before calling or texting, and mark anyone who says stop as "Do not call".
- **Google Maps import:** upload a CSV with name, phone, website and address columns. Google AI finds the owner and their YouTube channel, and businesses with no channel are skipped.

## The Google AI Chrome window

It stays **minimized** while it searches, so it does not cover your screen. If Google asks you to verify, the window comes back by itself and you get a phone alert. Solve it there, and it minimizes again.

To keep it visible while debugging, start the helper with `AI_WINDOW=shown`.

## Phone alerts

Needs-you alerts (a Google verification, drafts ready, autopilot stopped) go to Telegram as "ClipperCRM: ...". Test it with the **Test phone alert** button on the Email tab. If the alert says Google needs you, log in to your remote connection and solve it.

## If something is stuck

- **Not making drafts:** read the autopilot log on the Email tab. "No email on their own pages" means the lead has no public email. "Search not run, will try again later" means the helper was busy and it retries next round.
- **Google AI searches crash immediately:** the Google AI Chrome window can go stale after hours open. The helper now restarts it by itself. If it ever does not, stop everything and start it again.
- **Sheet link missing:** reload the CRM tab. The link fills in a short while after a lead's clips are made.
- **Two CRM tabs open:** close one. They share the same data and can save over each other.
- **Helper not running:** the page says so. Run the start command above.

## Settings that matter

- **Email tab:** Autopilot mode (save to drafts or send for real), Keep at most, Clips per round, Check every N minutes, auto-send toggle.
- **Sending:** 5 inboxes, warm-up limits per inbox, sending hours 9 to 5 Arizona time, a 60 to 90 second gap between sends.
- **Skip Microsoft-hosted mailboxes** is on by default because they filter cold mail harder.
- Settings and data live in your browser. Use Settings, **Export JSON**, to back them up.
