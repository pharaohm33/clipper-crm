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
| `{clip_link}` | the clip link, or all of them, one per line |
| `{clips}` | "a short clip", "a few short clips" or "three short clips" |
| `{they_are}` | "It is" for one clip, "They are" for several |
| `{personal_line}` | the note DeepSeek wrote about the clip (empty if none) |
| `{sender}` | your name |
| `{episode}` | the episode title (avoid: titles are long) |

Do NOT type your name block, postal address or opt out line. They are added at the bottom of every email automatically.

Hyphens and long dashes are turned into commas or spaces automatically, so the email reads naturally.

## Subject lines and the split test
- **Subject / Body** is version A. **Subject B / Body B** is version B. About half your leads get each.
- Leave Body B empty to test only the subject (recommended). Leave Subject B empty to test only the body.
- Change ONE thing at a time, and wait for about 100 emails per version before picking a winner. The **Results** card shows replies, opt outs and bounces per version.
- Short, specific subjects work best. Avoid "free", all caps, "!!", emojis, and "Re:" or "Fwd:".

## The personal note
- DeepSeek reads the words spoken in the clip and writes one or two sentences about one specific point.
- It is only used where you put `{personal_line}`. If a lead has no note, that paragraph simply disappears.
- Read every note in Preview. If one is wrong or odd, remove that lead for now or rewrite the line in the lead's data. The rules DeepSeek follows are at the top of `tools/personalize.py` (the `SYSTEM` text): change the tone there.
- Button **2b. Write personal notes** fills in notes for leads that already have a clip.

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
