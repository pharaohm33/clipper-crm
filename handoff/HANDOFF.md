# Handoff: Meta ads video maker

Repo: ~/clipper-crm (GitHub pharaohm33/cold-email-outreach-crm). Full earlier chat is NOT in git (large, holds lead data).

## Set up a computer (one command)
    bash tools/setup_video_tools.sh          # voice (Kokoro), recorder, ffmpeg, quality check
    bash tools/setup_video_tools.sh --dia    # also the slower cloned-voice engine (16 GB RAM or more)
Then start everything with tools/start_outreach.command (it uses tools/.venv and waits until the helper answers).
By hand, once per computer: in the CRM press "Connect Loom" and log in (the helper keeps its own Chrome profile).

## How a lead becomes a draft
1. CRM "make videos" -> helper POST /ads/video -> tools/ad_video.py: brand check by email domain, real ad counts, script from page facts only, voice, recorded page scroll with captions, photo bubble, sign up banner at the call to action.
2. Automatic check (ad_video.qa): the finished video's audio is transcribed and compared with the script, the ending must be there, the length sane, the banner on screen before the end. Result is sent with the video (qa).
3. A video that passes is approved by itself (CRM setting "Approve videos that pass the automatic check", on by default). One that fails shows "needs a look: <reason>" and waits for a human tick.
4. Approved -> uploaded to Loom (comment with the sign up link) -> email draft saved. Sending automatically approved videos is OFF unless "and send those too, even if I did not watch them" is ticked; videos a person ticked are sent as before.

## Voices (tools/ad_video.py, speak())
- Default: kokoro:am_michael, run locally from tools/.kokoro_venv through tools/kokoro_say.py (about 6 s for a script, real word times for captions). Falls back to the Kokoro server (Docker), then Microsoft HD voice.
- "dia": Emmanuel's cloned voice (seed 7), tools/dia_server.py keeps Dia loaded and starts by itself. One take per script (split only past ~125 words), every take is transcribed and voice-checked against tools/assets/dia_ref.wav and redone if it misreads, stalls, drifts to another voice or loses its ending. About 2.5 minutes per take on an M5 Max.
- SPEED = 1.25 in ad_video.py (1.0 = the voice's own speed).
- VibeVoice-Realtime was tried (tools/.vibevoice, ignored by git): fixed preset voices only, no cloning, not used.

## Start outreach button, HALCRUS leads and the scheduled-send queue (CRM, Meta Ads tab)
- "Start outreach": if fewer leads are ready than "Videos per press", it asks HALCRUS for more (tools/halcrus_leads.py: its own Chrome profile tools/.halcrus_profile, log in once with "Connect HALCRUS"; reads /leads with the page's tier dropdown (Hot by default), skips leads already in the CRM, "weaker fit" rows, repeat brand domains, and remembers the page it reached in tools/halcrus_state.json). Then it makes the videos (3 at a time, more rounds if a brand check rejects some), uploads to Loom, saves drafts and queues the sends.
- Scheduled sends live in the helper (tools/send_queue.py, file tools/send_queue.json, thread started by local_runner): each approved email gets a slot (now if inside the sending hours and an inbox has capacity left, else the next sending day, spread by min/max_delay_seconds and capped by the inboxes' warm-up and daily limits). They go out even if the CRM page is closed, as long as the helper runs and the Mac is awake.
- The queue is the memory of when each email goes out, kept until it is sent (sent entries 7 more days). States: scheduled, sending, sent, canceled, failed (3 refused sends), bounced, skipped. When one drops out the ones behind it move up; a send blocked by the day ending or a cap moves to the next free slot. A bounce found in the inbox marks it bounced and it is never retried. Cancel / Reschedule buttons are in the "Scheduled sends" table. The page applies the queue's state to the leads (sent, bounced, canceled), and a lead that was canceled, failed, bounced or skipped is never queued again by itself.
- Helper endpoints: /queue/add (needs confirm: true), /queue/list, /queue/cancel, /queue/reschedule, /halcrus/status, /halcrus/login, /halcrus/leads.
- Restart the helper after pulling these changes.

## Running by itself once you are logged in
- Logins you do once (CRM, Meta Ads tab): Connect Loom, Connect HALCRUS. Everything else runs without clicks.
- "Keep going by itself" (Start outreach card, on after the first Start press, off switch included): every 10 minutes while the CRM page is open, if fewer than N emails are scheduled or on their way (default 15), it finds leads in HALCRUS, makes videos, uploads, drafts and schedules more. Guards: it stops and alerts your phone if 5 videos wait for a human look, if Loom or HALCRUS needs a login, and waits 1 to 3 hours after a run that added nothing.
- The helper keeps the Mac from idle-sleeping (caffeinate, renewed) while any email is due in the next 13 hours, and releases it when the queue is empty. Closing a laptop lid still sleeps it unless it is on power with an external display.
- Phone alerts (Telegram, PHONE_BOT_TOKEN and PHONE_CHAT_ID in tools/.env): Loom or HALCRUS needs a login, a send failed for good, a send was skipped, bounces, and one summary at the end of each sending day.
- Default sending mode is "I press Send myself": the pipeline makes videos, uploads them to Loom, saves the drafts and approves them ahead of time, then notifies you (Mac and phone) once sending hours are open and at least X approved emails are ready (X is set in the Start card, default 10; again for every further X). The "Send N approved emails" button then schedules them (right away inside sending hours, otherwise from the next opening); you can cancel any in the Scheduled sends table. "Automatic" mode (untick "I press Send myself") schedules them with no question.
- Videos are deleted from this Mac as soon as Loom confirms the upload (they live in Loom); a failed upload keeps the file. Keep local copies: set keepLocalVideos in the CRM settings or KEEP_LOCAL_VIDEOS=1 for the helper.
- Follow-ups and replies run by themselves: the helper scans the sending inboxes for replies every 30 minutes (send_queue.scan_replies; a reply or opt-out is logged, opt-outs go on the do-not-contact list, the phone is alerted), and the page queues follow-up 1 (3 days after the first email) and follow-up 2 (7 days) through the same queue (ids like "<lead>#fu1"), never to anyone who replied, asked to stop, bounced or is on do-not-contact. Switch: "Send follow-ups by itself" in the Start card.
- "Growth guide" tab in the CRM: the plan for growing the sending side (rules, Workspace direct, Primeforge with the Gmail API, sending with the Mac off, what runs by itself), with sources. PrivateEmail has no confirmed server-side scheduled send, so the queue sends from the helper; for Mac-off sending see that tab (wake schedule with pmset, or an always-on machine).
- tools/install_autostart.sh (installed on this Mac): starts the helper at every login and restarts it if it stops; --open-crm also opens the CRM page at login (the keep-going loop runs in that page); --remove undoes it; --print shows what it writes.

## Photo
tools/assets/narrator.jpg is cropped with the face centered in the circle bubble.

## Notes
- Restart the helper after any tools/*.py change: kill $(lsof -ti :8765); tools/.venv/bin/python tools/local_runner.py
- The CRM data and lead CSVs are gitignored and not in the repo.
- Open items: leads need Loom links before drafts save (the pipeline now does the upload once Loom is connected); discard first-email drafts for Negative Underwear and Cabeau (already emailed from Gmail).
