# Quick start

Everything runs on your Mac. The CRM page is the control panel, a small helper on your computer does the work (Google AI searches, email, clips), and the clipper app makes the clips.

CRM: https://pharaohm33.github.io/cold-email-outreach-crm/

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

## Meta ads campaign (separate from the podcast clips)

Switch to **Meta ads** in the header. It has its own leads, emails and replies, and nothing from the podcast campaign is used.

1. **Meta Ads tab, Import:** choose `tools/ad_leads_portal.csv` (your HALCRUS portal leads) or `tools/ad_leads.csv`. Leads you already emailed from Gmail are marked and kept out of the first touch.
2. **Emails for this campaign:** edit the product name, your sign up link, and the seven templates (first email, follow up 1 after 3 days, follow up 2 after 7 days, and three reply templates). Pricing in the defaults is performance based: 20% of the money saved, nothing if nothing is saved. Press **Preview** to see the first email.
3. **Save the next 10 first emails as drafts**, then **Load my Meta drafts**, tick the ones you approve, and **Send the approved drafts**. Sends are one at a time, inside your sending hours and daily limits.
4. **Send follow ups that are due:** follow up 1 and 2 go only to people who were emailed and have not replied.
5. **Check replies:** DeepSeek reads each reply and picks one of your reply templates (confused, interested, ready). It only saves the answer as a **draft**. Opt-outs go on the do-not-contact list, and anything unclear is left for you.

The first email says you came across their company while looking at brands that advertise on Meta. Use the "we spoke already" wording (`tools/templates/meta_ads_optimization.md`, template 6) only after a real conversation.

## The Google AI Chrome window

It stays **minimized** while it searches, so it does not cover your screen, and it is minimized again whenever a search ends. If Google asks you to verify, you get a Mac banner and a phone alert, but the window does **not** pop up by itself: click the Google Chrome icon in the Dock, solve it, and it waits up to 5 minutes.

To keep it visible while debugging, start the helper with `AI_WINDOW=shown`. To make it pop up (once per run) when Google asks you to verify, start the helper with `AI_WINDOW_ON_VERIFY=show`.

## Phone alerts

Needs-you alerts (a Google verification, drafts ready, autopilot stopped) go to Telegram as "ClipperCRM: ...". Test it with the **Test phone alert** button on the Email tab. If the alert says Google needs you, log in to your remote connection and solve it.

## Audit outreach tab (coaches)

Cold email for fitness, weight loss and executive coaches, offering a free 3 minute video on where they lose high ticket inquiries. It is separate from the podcast leads but uses the same inboxes, warm-up caps, do-not-contact list and Unibox.

1. **Templates:** three starters are included. Each new prospect gets one active template (spread evenly, or pin one on the prospect). Edit the wording, the follow ups (3 and 7 days) and the per type lines ({client_type}, {leaks}) in the editor. Every prospect row shows which template and step it received, and the table shows sent, replied, interested and booked per template.
2. **Prospects:** paste lines like `Name | fitness / weight loss / executive | email | business | LinkedIn URL | website | one real sentence about them`. The "about them" sentence is what makes the first line personal; if it is blank that line is dropped.
3. **Send:** keep **Save as drafts** until you trust the wording, read them, then switch to **Send for real**. Follow up 1 and 2 only go to people who have not replied.
4. **When someone says yes:** record the video, paste its link in their row, and answer from the Unibox. Nothing is sent automatically to prospects.
5. **Find coaches (no LinkedIn login):** pick a type and optional city, press **Find coaches**. Google AI only suggests names and websites. A coach is kept only if their website loads, is about coaching and shows their name, and the email and phone come from that website's own pages (mailto and tel links, "call" or "text" numbers). Prospects that have a website but no email or phone get **Find emails and phones**. A phone is marked "mobile" only when the page calls it a cell, mobile or text number. A phone number alone can't tell mobile from landline, so check the National Do Not Call list before calling or texting.
6. **LinkedIn:** the **LinkedIn note** button copies a short note and opens their profile. You send it yourself (no automated LinkedIn messaging).
7. Compare templates only after about 100 first emails each; below that, differences can be luck. Change one thing at a time.

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
