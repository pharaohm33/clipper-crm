#!/usr/bin/env python3
"""Applies tools/outreach_settings.json to every template already in the Podcast Outreach folder of the clipper app
(new templates made by the helper get these automatically). Safe to re-run after you edit the JSON file.
    python3 tools/apply_outreach_settings.py            # apply
    python3 tools/apply_outreach_settings.py --dry-run  # just list what would change"""
import json, os, sys, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import local_runner as r


def main():
    dry = "--dry-run" in sys.argv
    code, d = r.app_call("/api/clip-templates", timeout=10)
    if code != 200:
        sys.exit(f"The clipper app is not reachable at {r.APP_URL}")
    wanted = r.outreach_settings()
    for t in d.get("templates", []):
        f = t.get("folder") or ""
        if not (f == r.OUT_FOLDER or f.startswith(r.OUT_FOLDER + "/")):
            continue
        have = t.get("settings") or {}
        diff = {k: v for k, v in wanted.items() if have.get(k) != v}
        print(f"{t['name']}: {len(diff)} setting(s) to change" + (f" {diff}" if diff and dry else ""))
        if diff and not dry:
            c, resp = r.app_call("/api/clip-templates/settings", {**have, **wanted, "slug": t["slug"]}, timeout=30)
            print("   ->", "ok" if c == 200 and resp.get("success") else f"FAILED {resp.get('error') or c}")


if __name__ == "__main__":
    main()
