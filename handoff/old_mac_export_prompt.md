# Prompt for Claude on the OLD Mac: export the email setup

Paste this into Claude on the old computer:

```text
In ~/clipper-crm/tools, create a zip at ~/Desktop/email_setup.zip containing exactly these files, skipping any that don't exist: email_accounts.json, email_log.jsonl, suppression.txt, .env, campaign_pause.json.

These files contain passwords, so do not print or read out their contents, and do not commit, upload or email anything. When it's done, tell me which files went into the zip with their sizes, how many lines email_log.jsonl has, and then reveal the zip in Finder so I can AirDrop it to my new Mac.
```

Then AirDrop `email_setup.zip` to the new Mac (it lands in Downloads) and run this on the NEW Mac:

```bash
unzip -o ~/Downloads/email_setup.zip -d ~/clipper-crm/tools/
```

Afterwards delete the zip from Downloads and the Desktop; it holds your inbox passwords. Nothing in it is ever committed (all five files are gitignored).
