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

## The two strategies (never mixed)
- Strategy 1 (plain first email, follow-ups 3 and 7 days) and Strategy 2 (the Loom: video, "{Weird|Strange|Odd|Important|Unusual|Quick} find in your ads" email (one word per recipient, fixed by the lead id so preview, send and follow-ups agree) with only the Loom link, Loom follow-ups 3 and 7 days) are separate. A lead is tagged (l.strategy: 'proposal' or 'loom'; stratOf() infers it for older leads) and the two lead pools exclude each other. The Loom template is no longer a "second touch" after another email; cold_email.plan refuses a first email of either kind within 90 days of any earlier first email, and a follow-up always uses the template of the first email actually sent.
- The Loom email, follow-ups and the manual Loom script are the Strategy 2 text from the client acquisition document (defaults in index.html; a saved copy of the OLD defaults is replaced, edited ones are kept). The automated video script (ad_video.build_script) is the same script, spoken as a recording; no pricing percentage, and the sign-up banner starts at "If you want to take a look at our website".
- Changed for accuracy: "I took a look at" instead of "I'm actually looking ... right now" in the recorded video; follow-up 2 no longer claims the video expires in 48 hours or that there is nothing being sold; it says there is no cost to take a look or start saving money on ads.
- Not loaded: the "We spoke already" wording of Strategy 1 (claims a conversation that did not happen).

## One button, the Unibox, and moving to automatic (Meta Ads tab)
- "↻ Load my Meta drafts + ..." is one button. Pick the template with the two buttons beside it: "2 · The Loom" (loads your drafts, finds leads if you are running low, makes the videos, uploads to Loom, saves the drafts, reloads the list) or "1 · First email" (loads your drafts, writes first-email drafts for fresh leads that are not in the Loom flow, reloads the list). "📥 Open Unibox" is next to it.
- The Unibox tab now exists in both campaigns. In Meta mode it reads the Meta drafts and replies (campaign sent to the helper), uses the Meta leads, and "Schedule the approved" puts the approved emails in the send queue (same rules as everything else). Edits you save in the Unibox are what is sent (body_override / subject_override in the lead payload). Removing a draft removes the lead from all lead pools (removedAt). Marking a reply Interested or Not Interested stops follow-ups (replied).
- The Start card counts how your approvals go (as written, edited, removed). When about 20 or more are 90% as written it suggests unticking "I press Send myself" to run it all day (automatic mode). Add inboxes after that (Growth guide).

## Loom step (tools/loom_upload.py), as of the Oct 2026 Loom page
- Loom's video page changed: the comment box is now behind the "Comment" button (a composer with a "Comment at m:ss" button), comments are listed in the Activity tab, and links live in a "Links" area ("Add a link": Link URL, Title, Pin this link, Save). The account has the sign-up link as a default link, so new videos already show it; the step checks for it and only adds it (pinned) when missing, keeps "Only show links at the end of the video" OFF so the link stays on the video, and reports any other links listed.
- The comment with the sign-up link is stamped at the call to action (video JSON link_from: right after the video says nothing is charged up front / only performance), found by playing the video to that second before opening the composer. A comment that is already there is detected through the Activity tab, so a retry never posts twice.
- Every upload's link is saved in tools/loom_uploads.json (git-ignored) as soon as it shows in the library, and a retry reuses it (no second upload, even if the local file is gone). A failure after the upload still returns the link. A new press of the main button retries leads whose Loom step failed.
- The Instagram story card is collapsible (closed by default) like the templates.

## Meta Ads tab: numbered workflow, email eligibility, approving videos
- The Start card is now "Loom outreach, step by step": 1 Connect (Loom, HALCRUS, email), 2 Make the videos (template buttons, videos per press, the big button, live status), 3 Check the videos (list with per-video "I watched it, approve", "approve all", "Upload to Loom + save drafts now"), 4 Review the emails (Unibox button and the drafts to review), 5 Send (approved emails, scheduled sends table). "Automatic mode and settings" is a collapsed section under it. Email templates, the campaign list, the Google AI prompt, the Instagram card and "Manual Loom tools" are collapsed below.
- A video you approve by hand (per video or approve all) counts as watched; nothing is sent from an approved video until step 5 unless automatic mode is on.
- Microsoft-hosted recipients: the Loom template (meta-loom, skip_providers: []) is exempt from the provider skip; Strategy 1 still skips them.
- HALCRUS leads are "trusted" (payload trusted_source): they ignore the provider skip as long as the address passes email_check.classify (valid mail server, not a role/junk pattern). Before any video is made, startOutreach checks each new HALCRUS lead (checkLeadEmails -> /emails/check, optionally asks Google AI via tools/email_ai_check.py in the ~/.clipper_chrome_profile browser, about 45 s each) and asks the engine whether the Loom email would actually be sent (loomEligible -> /email/preview), so no video is made for someone who would not be emailed. Ineligible leads are marked lead.ineligible and left out of the pool.
- Settings (Automatic mode and settings): "Trust HALCRUS emails" (S.settings.trustHalcrus, default on) and "Also check each new HALCRUS email with Google AI" (S.settings.aiEmailCheck, default on). Turn the AI check off once it stops being useful; HALCRUS likely cleans its emails.

## Faster runs: stock goal, bigger rounds (Oct 17)
- One-time page migration (S.settings.fastMig): 10 videos per press, auto-schedule (sendMode auto: approved emails are scheduled by themselves), keep 2 days of emails saved, Google AI email check OFF. The quick built-in email check always runs.
- "Emails saved" = Loom leads with a draft saved or scheduled and not sent. Goal = keepDays (default 2) x what the enabled inboxes may send today (dailyCap, from the helper's inbox caps). The automatic top-up (autoKeep) runs startOutreach(min(10, goal - saved)) and, while it makes progress and is below the goal, goes again after 20 s; with no progress it waits 3 h.
- startOutreach: up to 14 rounds of 5 videos, keeps a buffer of 2x the leads it needs (asks HALCRUS for at least 20 at a time), remembers which leads were already confirmed emailable (lead.eligOk, 24 h) and which had no video (lead.video.reason, never retried). Leads that fail the Ad Library / brand check are the main loss (about 60% in the last run).
- tools/email_ai_check.py: reports the quick check per lead at once, then asks Google AI 5 addresses per (single-line) question and reports each lead as it is answered, so a cut-short run keeps what it learned. Turn it on in "Automatic mode and settings".
- Loom upload: finds the new video as the library card that was not there before (Loom auto-renames uploads), retries the rename, and Stop cancels it.

## Ad Library lookup and template tracking (Oct 17)
- ad_video.make(): US Ad Library first; if nothing there is this brand (no candidates, or the brand check fails), it looks in the all-countries Ad Library, but only at pages named like the brand (finds UK/Canadian shops such as homemadebrownie.co.uk). HALCRUS rows carry no ad data (the "why" text is the same generic scoring blurb), so nothing in them can predict who advertises.
- Each lead in the advertisers table shows its template: Template 2 (Loom) sent / scheduled / draft saved, Template 1 sent, "Free for Template 1" (no Loom possible: no Meta ads found or ads are not this brand), Not used yet, or Do not email. Filter buttons above the table. The "1 · First email" button writes drafts for the Free leads first (metaFresh sorts them first and skips leads whose email is not usable). HALCRUS leads now also keep their category (l.category) for later learning which categories advertise.

## Photo
tools/assets/narrator.jpg is cropped with the face centered in the circle bubble.

## Notes
- Restart the helper after any tools/*.py change: kill $(lsof -ti :8765); tools/.venv/bin/python tools/local_runner.py
- The CRM data and lead CSVs are gitignored and not in the repo.
- Open items: leads need Loom links before drafts save (the pipeline now does the upload once Loom is connected); discard first-email drafts for Negative Underwear and Cabeau (already emailed from Gmail).
