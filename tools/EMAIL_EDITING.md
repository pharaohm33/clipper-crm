# Editing your email (simple guide)

Where: the CRM website, **Email** tab, the **Your email** box. Changes save by themselves. Always press **3. Preview emails** afterwards and read two or three before sending.

## Spintax: how to make every email a little different
Put the options inside curly braces, separated by a vertical bar:

    {Hi|Hey|Hello} there,

Each lead gets ONE of the options at random, and the same lead always gets the same one (so Preview shows exactly what will be sent).

Rules:
- Use 2 to 4 options per group. More than that is hard to read and test.
- Do not put one group inside another: `{Hi|{Hey|Yo}}` will NOT work.
- Do not put a token (see below) inside a group: `{Hi {name}|Hey}` will NOT work. Put the token outside: `{Hi|Hey} {name},`.
- Keep the meaning the same in every option. Change wording, not the offer.
- Do not spin the subject line while you are split testing (see below).

## Tokens: pieces filled in for each lead
| Write this | It becomes |
|---|---|
| `{name}` | the podcast's name |
| `{niche}` | the niche, like "real estate" |
| `{topic}` | a short phrase DeepSeek writes about one point in the clip, like "the part where you buy near Music Row before you move there" (falls back to "your recent episode") |
| `{clip_link}` | clip links, one per line. The default email has NO links, on purpose |
| `{clips}`, `{they_are}` | wording that adapts to how many links there are (only matter if you add links) |
| `{sender}` | your name |
| `{episode}` | the episode title (avoid: titles are long) |

Do NOT type your name block, postal address or opt out line. They are added at the bottom of every email automatically.

Hyphens and long dashes are turned into commas or spaces automatically, so the email reads naturally.

## Subject lines and the split test
- **Subject / Body** is version A. **Subject B / Body B** is version B. About half your leads get each.
- Leave Body B empty to test only the subject (recommended). Leave Subject B empty to test only the body.
- Change ONE thing at a time, and wait for about 100 emails per version before picking a winner. The **Results** card shows replies, opt outs and bounces per version.
- Short, specific subjects work best. Avoid "free", all caps, "!!", emojis, and "Re:" or "Fwd:".

## The topic phrase
- DeepSeek reads the words spoken in the clip and writes the short phrase that fills "I really liked ____" in the email.
- It is used where you put `{topic}`. If a lead has none, the email says "your recent episode" instead.
- Read every phrase in Preview. If one is wrong or odd, skip that lead for now. The rules DeepSeek follows are at the top of `tools/personalize.py` (the `SYSTEM` text): change the tone there.
- Button **2b. Write personal notes** fills in notes for leads that already have a clip.

## No links in the first email
The first email asks "Do you want me to send it over?" and has no links, because links are a spam signal. The clips are made as private drafts in the template's folder. When someone says yes, open the **Email** tab: the **They said yes** card (leads marked Replied or Interested) has **Get links + copy reply**. It makes view links for that lead's clips and copies a ready reply to paste.

## When someone says yes (automatic reply)
Press **6. Check replies**. For each reply, DeepSeek decides if they clearly said yes, no, asked a question, or something else.
- **Clear yes (80%+ sure):** a reply is written from the same inbox that sent the first email, in the same thread, with a link to a page of their clips (named after their podcast), your phone number at the bottom, and a line inviting them to tell you if they like it and to ask for more. The clips only become public at this moment.
- **Clear no:** they go on the do not contact list.
- **Questions or anything unclear:** left for you, listed as "Needs you".
- **Draft or send:** `python3 tools/setup_email.py`, option 3, asks. **draft** (the starting setting) saves the reply in that inbox's Drafts for you to look at and send. **send** sends it right away. Keep it on draft until a few replies have looked right.
- **Your phone number** is set in the same place. Without it, nothing is written.
- The reply wording is `REPLY_BODY` at the top of `tools/auto_reply.py` (spintax works).

## Follow ups
They go out after 3 and 7 days if there was no reply, in the same email thread. Their wording is in `tools/cold_email.py` (the `FOLLOWUPS` list). Spintax and tokens work there too.

## Good and bad
Good: `{Hi|Hey} there, I caught your episode on {niche} and {loved it|really enjoyed it}.`
Bad: `{Hi|Hey|Hello|Hola|Yo|Greetings|Howdy} {name}!!!` (too many options, shouty)
Bad: `{FREE clips|Free clips!!!}` in the subject (looks like spam)

## Safe checklist before a real send
1. Preview: read 3 emails start to finish, check the links open.
2. Postal address is real, and Reply-To is on a domain you own.
3. Start small (the app's daily caps do this), then check **Results** after a few days.
