#!/usr/bin/env python3
"""
Local helper so the website's "Run live" button can start google_ai_to_crm.py on your computer.

Start it once and leave the window open:
    cd ~/clipper-crm && python3 tools/local_runner.py

It only listens on 127.0.0.1 and only accepts requests from this site (or localhost). Your keys live in
tools/.env (copy tools/.env.example) and are never sent to the browser.
"""
import json, os, re, subprocess, sys, threading, time
import urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cold_email, email_finder, personalize, auto_reply
SCRIPT = os.getenv("RUNNER_SCRIPT", str(HERE / "google_ai_to_crm.py"))
PORT = int(os.getenv("RUNNER_PORT", "8765"))
APP_URL = os.getenv("CLIPPER_URL", "http://127.0.0.1:5001").rstrip("/")
GRAB = os.getenv("GRAB_SCRIPT", str(HERE / "grab_sample.sh"))
SAMPLES = os.getenv("SAMPLES_DIR", str(Path.home() / "Downloads" / "clip-samples"))
OUT_FOLDER = os.getenv("SAMPLES_FOLDER", "Podcast Outreach")
SETTINGS_FILE = Path(os.getenv("OUTREACH_SETTINGS_FILE", str(HERE / "outreach_settings.json")))
_DEFAULT_SETTINGS = {"captions": True, "quality": "high", "silence_cut": True, "silence_secs": "0.8", "quote": True,
                     "reuse": False, "viral": False, "full_thought": True, "host_question": False, "hook": True,
                     "ai": True, "after": "draft"}
REVEAL_CMD = os.getenv("REVEAL_CMD", "open -R").split()
ALLOWED = {"https://pharaohm33.github.io"}
STATE = {"running": False, "log": [], "proc": None}
LOCK = threading.Lock()


def load_env():
    f = HERE / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def origin_ok(origin):
    if not origin:
        return True
    return origin in ALLOWED or re.match(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$", origin) is not None


def clean(s, n=80):
    return re.sub(r"[^\w\s.,'&/+-]", "", str(s))[:n].strip()


def run_job(argv):
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    try:
        proc = subprocess.Popen([sys.executable, "-u", SCRIPT, *argv], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, env=env, cwd=str(HERE.parent))
        STATE["proc"] = proc
        for line in proc.stdout:
            STATE["log"].append(line.rstrip())
            if "asking you to verify" in line:
                if phone_notify("Google needs you", "Google is asking for a verification and the lead search is waiting (up to 5 minutes). " + REMOTE_HINT, key="captcha"):
                    STATE["log"].append("[runner] sent a phone alert")
        proc.wait()
        STATE["log"].append(f"[runner] finished (exit {proc.returncode})")
    except Exception as e:
        STATE["log"].append(f"[runner] failed to start: {e}")
    finally:
        STATE["running"] = False


def run_fit(path):
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    try:
        proc = subprocess.Popen([sys.executable, "-u", str(HERE / "fit_check.py"), path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, env=env, cwd=str(HERE))
        STATE["proc"] = proc
        for line in proc.stdout:
            STATE["log"].append(line.rstrip())
            if "asking you to verify" in line:
                if phone_notify("Google needs you", "Google is asking for a verification and the fit check is waiting (up to 5 minutes). " + REMOTE_HINT, key="captcha"):
                    STATE["log"].append("[runner] sent a phone alert")
        proc.wait()
        STATE["log"].append(f"[runner] fit check finished (exit {proc.returncode})")
    except Exception as e:
        STATE["log"].append(f"[runner] fit check failed to start: {e}")
    finally:
        STATE["running"] = False


def outreach_settings():
    """The clipper settings every outreach template starts with (tools/outreach_settings.json; edit that file to change them)."""
    try:
        return {**_DEFAULT_SETTINGS, **json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(_DEFAULT_SETTINGS)


def app_call(path, payload=None, timeout=5):
    """JSON call to the local clipper app. Returns (status_code, dict) or (0, {}) if it is unreachable."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(APP_URL + path, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception:
        return 0, {}


AWAKE = {"proc": None, "until": 0}


RISKY_TLDS = {"online", "site", "space", "store", "world", "xyz", "top", "click", "club", "shop", "icu", "buzz", "monster", "cyou", "sbs", "quest", "rest", "fun", "work", "win", "bid", "vip", "live", "website", "tech", "cfd"}
PHONE_LAST = {}
REMOTE_HINT = os.getenv("PHONE_REMOTE_HINT", "To fix it from your phone: open RVNC Viewer, connect to your Mac (emmanuels-macbook-air.taile1d9f0.ts.net or its Tailscale address), find the Chrome window and complete the check there.")


def phone_ready():
    return bool(os.getenv("PHONE_BOT_TOKEN") and os.getenv("PHONE_CHAT_ID"))


def phone_notify(title, message, key=None, every=600):
    """A push message to your phone through your Telegram bot. The same alert is not repeated within `every` seconds. Returns True if sent."""
    if not phone_ready():
        return False
    k = key or title
    if time.time() - PHONE_LAST.get(k, 0) < every:
        return False
    PHONE_LAST[k] = time.time()
    text = f"ClipperCRM: {title}\n{message}"
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{os.environ['PHONE_BOT_TOKEN']}/sendMessage",
                                     data=json.dumps({"chat_id": os.environ["PHONE_CHAT_ID"], "text": text[:900]}).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
        return True
    except Exception:
        return False


def awake_status():
    """Is this tool keeping the Mac from sleeping (a 'caffeinate' it started), how long is left, and will closing the lid still sleep it."""
    p = AWAKE["proc"]
    on = bool(p and p.poll() is None)
    out = {"on": on, "seconds_left": max(0, int(AWAKE["until"] - time.time())) if on else 0, "on_ac": None, "battery": None, "lid_sleep_disabled": False}
    if sys.platform == "darwin":
        try:
            b = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5).stdout
            out["on_ac"] = "AC Power" in b
            m = re.search(r"(\d+)%", b)
            out["battery"] = int(m.group(1)) if m else None
            s = subprocess.run(["pmset", "-g"], capture_output=True, text=True, timeout=5).stdout
            m = re.search(r"SleepDisabled\s+(\d)", s)
            out["lid_sleep_disabled"] = bool(m and m.group(1) == "1")
        except Exception:
            pass
    return out


def awake_set(on, minutes=180):
    """Starts or stops keeping the Mac awake. It always has an end time, so it cannot be left on forever by accident."""
    p = AWAKE["proc"]
    if p and p.poll() is None:
        p.terminate()
    AWAKE["proc"] = None
    if on and sys.platform == "darwin":
        minutes = max(5, min(int(minutes or 180), 720))
        AWAKE["proc"] = subprocess.Popen(["caffeinate", "-dimsu", "-t", str(minutes * 60)])
        AWAKE["until"] = time.time() + minutes * 60
    return awake_status()


def clipper_status():
    code, d = app_call("/api/clipper/status", timeout=2)
    if code != 200:
        return {"state": "off", "url": APP_URL}
    return {"state": "busy" if d.get("running") else "on", "stage": d.get("stage"), "message": d.get("message"),
            "pct": d.get("pct"), "error": d.get("error"), "template_slug": d.get("template_slug"), "url": APP_URL}


YT_RE = re.compile(r"^https://((www|m)\.)?(youtube\.com|youtu\.be)/\S+$")
TIME_RE = re.compile(r"^\d{1,2}(:\d{2}){1,2}$")


def sample_templates():
    code, d = app_call("/api/clip-templates", timeout=5)
    if code != 200:
        return None
    out = []
    for t in d.get("templates", []):
        f = t.get("folder") or ""
        if f == OUT_FOLDER or f.startswith(OUT_FOLDER + "/"):
            vp = t.get("video_path") or ""
            out.append({"slug": t.get("slug"), "name": t.get("name"), "folder": f, "video_path": vp,
                        "dir": str(Path(vp).parent) if vp else "", "duration": t.get("duration")})
    return out


def log(msg):
    STATE["log"].append(msg)


def _download(url, start, end):
    """Downloads a slice of a YouTube video. Returns the saved file path, or None after logging why not."""
    log(f"[runner] downloading {start} to {end} ...")
    env = {**os.environ, "NO_OPEN": "1"}
    p = subprocess.run(["bash", GRAB, url, start, end, SAMPLES], capture_output=True, text=True, env=env, timeout=1800)
    saved = [l[6:].strip() for l in p.stdout.splitlines() if l.startswith("Saved: ")]
    if p.returncode != 0 or not saved:
        log("[runner] download failed. " + (p.stderr.strip().splitlines() or ["yt-dlp gave no details"])[-1])
        return None
    video = saved[-1]
    log(f"[runner] saved {video}")
    return video


def _prepare(url, start, end, name, folder=None):
    """Downloads a slice of a YouTube video and saves it as a NEW template in the clipper (transcribes it once).
    Waits while the clipper is busy. Returns (video_path, slug) or None after logging why it could not."""
    video = _download(url, start, end)
    return _create_template(video, name, folder) if video else None


def _create_template(video, name, folder=None):
    """Saves an already downloaded slice as a NEW template in the clipper and waits for it to be transcribed."""
    waited, announced = 0, False
    while True:
        st = clipper_status()
        if st["state"] == "off":
            log(f"[runner] the clipper app is off ({APP_URL}). The clip source is saved here, start the app and click again:\n   {video}")
            return None
        if st["state"] == "on":
            code, resp = app_call("/api/clip-templates/create", {**outreach_settings(), "name": name, "path": video, "folder": folder or OUT_FOLDER}, timeout=30)
            if code == 200 and resp.get("success"):
                break
            if code != 409:
                log(f"[runner] clipper rejected the template: {resp.get('error') or code}")
                return None
        if waited >= 900:
            log("[runner] clipper stayed busy for 15 minutes, giving up. The file is saved:\n   " + video)
            return None
        if not announced or waited % 60 == 0:
            log(f"[runner] clipper is busy ({st.get('message') or 'working'}), waiting for it to finish ...")
            announced = True
        time.sleep(10)
        waited += 10
    log("[runner] template is being created (transcribing the slice) ...")
    last = ""
    for _ in range(1800):
        time.sleep(1)
        st = clipper_status()
        if st["state"] == "off":
            log("[runner] lost contact with the clipper app.")
            return None
        if st.get("message") and st["message"] != last:
            last = st["message"]
            log(f"   clipper: {last}")
        if st["state"] == "on":
            break
    st = clipper_status()
    if st.get("error"):
        log(f"[runner] the clipper reported an error: {st['error']}")
        return None
    return video, (st.get("template_slug") or "")


def run_send(url, start, end, name, folder=None):
    """Download a slice of a YouTube video, then save it as a NEW template in the clipper (no clips are generated:
    you change the rules there and press Generate yourself)."""
    try:
        got = _prepare(url, start, end, name, folder)
        if got:
            video, slug = got
            log("RESULT " + json.dumps({"slug": slug, "name": name, "video": video, "dir": str(Path(video).parent), "folder": folder or OUT_FOLDER}))
            log(f"[runner] DONE. Template \"{name}\" is in the clipper (folder: {folder or OUT_FOLDER}). Open it, adjust the rules, then press Generate.")
    except Exception as e:
        log(f"[runner] failed: {e}")
    finally:
        STATE["running"] = False


# ----------------------------------------------------------------------------------- automatic sample-clip pipeline
PIPE = {"stop": False}
REPO = Path(os.getenv("CLIPPER_REPO", str(Path.home() / "instagram-video-generator")))


def video_duration(url):
    """Length of a YouTube video in seconds (None if it can't be read)."""
    try:
        out = subprocess.run([sys.executable, "-m", "yt_dlp", "--no-playlist", "-q", "--no-warnings", "--extractor-args",
                              "youtube:player_client=android", "--print", "duration", url],
                             capture_output=True, text=True, timeout=90).stdout.strip().splitlines()
        return float(out[-1]) if out else None
    except Exception:
        return None


def pick_range(duration, minutes=5):
    """A slice that skips the intro and ad reads: about 20 percent in (never before 2:00), kept inside the episode."""
    length = int(minutes * 60)
    if not duration or duration < 120:
        return 600, 600 + length
    if duration < length + 90:
        return 0, int(duration) - 2
    start = int(max(120, min(duration * 0.2, duration - length - 30)))
    return start, int(min(duration - 5, start + length))


def _mmss(sec):
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def run_pipeline(leads, minutes=5, clips=1, after=None, folder=None, share=False):
    """For each lead in turn: pick a slice, download it, make the template, generate the clip, put it on a shareable
    link. One 'PIPE {json}' line per finished lead; the website saves it on the lead. Contact is still up to you."""
    def fetch(ld):
        """Picks the slice and downloads it (needs no clipper), so it can happen while the clipper is busy with another lead."""
        try:
            if ld.get("start") and ld.get("end"):
                s0, e0 = ld["start"], ld["end"]
            else:
                s_sec, e_sec = pick_range(video_duration(ld["url"]), minutes)
                s0, e0 = _mmss(s_sec), _mmss(e_sec)
            return s0, e0, _download(ld["url"], s0, e0)
        except Exception as e:
            return None, None, ("ERR", str(e)[:150])

    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(max_workers=1)
    pending = {}
    try:
        PIPE["stop"] = False
        for i, ld in enumerate(leads, 1):
            if PIPE["stop"]:
                log("[runner] stopped.")
                break
            name = f"Sample {ld.get('name') or ld['id']}"[:60]
            log(f"[{i}/{len(leads)}] {ld.get('name')}")
            try:
                s0, e0, video0 = (pending.pop(i).result() if i in pending else fetch(ld))
                if isinstance(video0, tuple):
                    raise RuntimeError(video0[1])
                if i < len(leads):
                    pending[i + 1] = pool.submit(fetch, leads[i])  # download the next slice while this one is processed
                got = _create_template(video0, name, folder) if video0 else None
                if not got:
                    log(f"PIPEFAIL {json.dumps({'id': ld['id'], 'why': 'could not prepare the slice'})}")
                    continue
                video, slug = got
                body = {"slug": slug, "count": max(1, int(clips))}
                if after is not None:
                    body["after"] = after
                log("   generating the clip ...")
                code, resp = app_call("/api/clip-templates/generate", body, timeout=60)
                if code != 200 or not resp.get("success"):
                    log(f"PIPEFAIL {json.dumps({'id': ld['id'], 'why': resp.get('error') or f'clipper said {code}'})}")
                    continue
                last = ""
                for _ in range(2700):
                    time.sleep(1)
                    c2, raw = app_call("/api/clipper/status", timeout=10)
                    if c2 != 200:
                        break
                    if raw.get("message") and raw["message"] != last:
                        last = raw["message"]
                        log(f"   clipper: {last[:100]}")
                    if not raw.get("running"):
                        break
                if raw.get("error") or not raw.get("outputs"):
                    log(f"PIPEFAIL {json.dumps({'id': ld['id'], 'why': raw.get('error') or 'no clip came out (the slice may have no strong moment)'})}")
                    continue
                outs = list(raw["outputs"])[:max(1, int(clips))]
                infos = list(raw.get("clips") or [])
                files, links, titles = [], [], []
                for k, out in enumerate(outs):
                    files.append(str(REPO / "opencut-exports" / out))
                    titles.append((infos[k] if k < len(infos) else {}).get("title", ""))
                    if not share:
                        continue  # the clips stay private drafts in the template's folder; links are made on request (/clips/share)
                    c3, shared = app_call("/api/outreach/share-clip", {"id": f"opencut-exports/{out}", "name": f"{ld.get('name')} - clip {k + 1}"}, timeout=300)
                    if c3 == 200 and shared.get("success"):
                        links.append(shared.get("link", ""))
                    else:
                        log(f"   (could not make a share link for clip {k + 1}: {shared.get('error') or c3})")
                first = infos[0] if infos else {}
                clip_file = files[0] if files else str(REPO / "opencut-exports" / outs[0])
                link = links[0] if links else ""
                ctext = clip_text_from_template(slug, first.get("real_start", first.get("start")), first.get("real_end", first.get("end"))) if first.get("start") is not None else ""
                personal = personal_note(ld, Path(clip_file).name, first.get("title", ""), first.get("hook", ""), ctext)
                log("PIPE " + json.dumps({"id": ld["id"], "slug": slug, "video": video, "dir": str(Path(video).parent), "clip": clip_file,
                                          "title": first.get("title", ""), "hook": first.get("hook", ""), "link": link, "personal": personal,
                                          "links": links, "files": files, "titles": titles, "yt_start": _yt_start(s0, first.get("start")),
                                          "range": f"{s0}-{e0}", "name": name}))
            except Exception as e:
                log(f"PIPEFAIL {json.dumps({'id': ld.get('id'), 'why': str(e)[:200]})}")
        log("[runner] pipeline finished.")
    finally:
        pool.shutdown(wait=False)
        STATE["running"] = False


def clip_text_from_template(slug, start, end):
    """The words spoken between start and end, read from the template's saved transcript (the same transcription the clip was cut from).
    Returns '' when it cannot be read, and the caller falls back to listening to the clip again."""
    try:
        f = REPO / "generated_content" / "clip_templates" / f"{slug}.transcript.json"
        segs = json.loads(f.read_text(encoding="utf-8"))
        s0, e0 = float(start), float(end)
        words = [w["w"] for seg in segs for w in (seg.get("words") or []) if s0 - 0.05 <= float(w["s"]) < e0]
        if not words:
            words = [seg["text"] for seg in segs if float(seg["e"]) > s0 and float(seg["s"]) < e0]
        return " ".join(words).strip()
    except Exception:
        return ""


def _yt_start(slice_start, clip_start):
    """Seconds into the YouTube episode where the first clip begins (slice start like '7:01' plus the clip's offset inside the slice)."""
    try:
        base = sum(int(x) * 60 ** i for i, x in enumerate(reversed(str(slice_start).split(":"))))
        return int(base + float(clip_start or 0))
    except Exception:
        return None


def personal_note(ld, clip_name, title, hook, text=""):
    """Reads the words spoken in the clip (the clipper's own transcript, the same one the clip editor shows), then asks DeepSeek for
    one specific note about it. Returns '' if anything is missing; the email still works without it."""
    if len(text.split()) < 25:
        code, w = app_call("/api/clip-edit/words", {"id": f"opencut-exports/{clip_name}"}, timeout=900)
        if code != 200 or not w.get("success"):
            log(f"   (no personal note: could not read the clip's words: {(w or {}).get('error') or code})")
            return ""
        text = w.get("text", "")
    line = personalize.write_line(ld.get("name") or "", ld.get("epTitle") or "", title, hook, text)
    if not line:
        log("   (no personal note: not enough to say, or no DeepSeek key found)")
    return line


def run_personalize(leads):
    """For leads that already have a clip: writes the personal note. One 'PERSONAL {json}' line each."""
    try:
        for ld in leads:
            if PIPE["stop"]:
                log("[runner] stopped.")
                break
            name = Path(str(ld.get("clipFile") or "")).name
            if not name:
                continue
            log(f"[runner] writing a personal note for {ld.get('name')}")
            line = personal_note(ld, name, ld.get("clipTitle") or "", ld.get("clipHook") or "")
            log("PERSONAL " + json.dumps({"id": ld["id"], "line": line}))
        log("[runner] personal notes finished.")
    finally:
        STATE["running"] = False


def run_find_emails(leads):
    """Looks for public contact emails, three leads at a time (each browser search is mostly waiting on pages)."""
    from concurrent.futures import ThreadPoolExecutor
    try:
        def one(item):
            i, ld = item
            if PIPE["stop"]:
                return i, ld, None
            try:
                return i, ld, email_finder.find_email(ld.get("name") or "", ld.get("url") or "", ld.get("web") or "", ld.get("episode") or "", log=lambda m: None)
            except Exception as e:
                return i, ld, {"email": "", "error": str(e)[:80]}
        with ThreadPoolExecutor(max_workers=3) as pool:
            for i, ld, got in pool.map(one, list(enumerate(leads, 1))):
                if got is None:
                    continue
                if got.get("email"):
                    log(f"[{i}/{len(leads)}] {ld.get('name')}: {got['email']} ({got['source']})")
                    log("EMAILFOUND " + json.dumps({"id": ld["id"], "email": got["email"], "source": got["source"]}))
                else:
                    log(f"[{i}/{len(leads)}] {ld.get('name')}: no public contact email found")
                    log("EMAILNONE " + json.dumps({"id": ld["id"]}))
        log("[runner] email search finished.")
    finally:
        STATE["running"] = False


def run_email(leads, template, mode, limit, ignore_window, step):
    try:
        PIPE["stop"] = False
        cold_email_sleep = lambda secs: [time.sleep(1) for _ in range(int(secs)) if not PIPE["stop"]]
        results = cold_email.run(leads, template, mode, limit=limit, ignore_window=ignore_window, step=step, log_fn=log, sleep=cold_email_sleep)
        for r in results:
            log("EMAIL " + json.dumps({k: r.get(k) for k in ("id", "to", "from", "status", "why", "subject", "step", "message_id")}))
        log(f"[runner] done: {sum(1 for r in results if r['status'] in ('sent', 'drafted'))} {mode} / {sum(1 for r in results if r['status'] == 'skip')} skipped / {sum(1 for r in results if r['status'] == 'failed')} failed")
    except Exception as e:
        log(f"[runner] email run stopped: {e}")
    finally:
        STATE["running"] = False


def email_status():
    cfg = cold_email.load_config()
    log_ = cold_email.read_log()
    problems = []
    if not cfg.get("accounts"):
        problems.append("add at least one sending inbox in tools/email_accounts.json (copy email_accounts.example.json)")
    if not (cfg.get("postal_address") or "").strip() or "mailing address" in cfg.get("postal_address", ""):
        problems.append("add your real postal address (cold email law requires it in every email)")
    if not (cfg.get("sender_name") or "").strip() or cfg.get("sender_name") == "Your Name":
        problems.append("add your name as sender_name")
    warnings = []
    rt = (cfg.get("reply_to") or "").lower()
    if rt and rt.split("@")[-1] in ("gmail.com","googlemail.com","yahoo.com","outlook.com","hotmail.com","live.com","icloud.com","aol.com","proton.me","protonmail.com"):
        warnings.append(f"Replies go to a free address ({rt}). Spam filters penalize a Gmail/Yahoo Reply-To on a different From domain (mail-tester: -2.5). Before real outreach, set Reply-To to a mailbox on a domain you own (python3 tools/setup_email.py, option 4).")
    risky = sorted({a["email"].split("@")[1].rsplit(".", 1)[-1] for a in cfg.get("accounts", [])} & RISKY_TLDS)
    if risky:
        warnings.append("Some sending domains end in " + ", ".join("." + t for t in risky) + ". Spam filters distrust these endings (mail-tester scored them 6 out of 10, about 3.5 points lost to the ending alone). A .com ending avoids that. Authentication and the email text are fine.")
    if not (cfg.get("phone") or "").strip():
        warnings.append("Add your phone number (python3 tools/setup_email.py, option 3). Automatic replies to people who say yes need it, and nothing is written without it.")
    caps = cold_email.capacity(cfg, log_)
    return {"warnings": warnings, "auto_reply": "send" if cfg.get("auto_reply") == "send" else "draft", "ready": not problems, "problems": problems, "inboxes": caps, "capacity_left": sum(max(0, c["cap"] - c["sent_today"]) for c in caps),
            "suppressed": len(cold_email.suppressed()), "suppressed_list": sorted(cold_email.suppressed())[:2000], "in_send_window": cold_email.in_window(cfg),
            "window": cfg.get("send_window") or {"start_hour": 9, "end_hour": 17}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj=None):
        origin = self.headers.get("Origin", "")
        body = json.dumps(obj or {}).encode()
        self.send_response(code)
        if origin and origin_ok(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _guard(self):
        if not origin_ok(self.headers.get("Origin", "")):
            self._send(403, {"error": "origin not allowed"})
            return False
        return True

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        if not self._guard():
            return
        u = urlparse(self.path)
        if u.path == "/status":
            self._send(200, {"ok": True, "phone": phone_ready(), "running": STATE["running"], "lines": len(STATE["log"]),
                             "configured": bool(os.getenv("CRM_SYNC_URL") and os.getenv("CRM_SYNC_PASSWORD")), "phone": phone_ready(),
                             "yt": bool(os.getenv("YT_API_KEY"))})
        elif u.path == "/awake":
            self._send(200, awake_status())
        elif u.path == "/clipper/templates":
            t = sample_templates()
            self._send(200 if t is not None else 503, {"templates": t or [], "folder": OUT_FOLDER, **({} if t is not None else {"error": "clipper is off"})})
        elif u.path == "/email/status":
            self._send(200, email_status())
        elif u.path == "/clipper/status":
            self._send(200, clipper_status())
        elif u.path == "/log":
            since = int(parse_qs(u.query).get("since", ["0"])[0] or 0)
            self._send(200, {"lines": STATE["log"][since:], "next": len(STATE["log"]), "running": STATE["running"]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._guard():
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"error": "bad json"})
        if self.path == "/stop":
            p = STATE.get("proc")
            if p and STATE["running"]:
                p.terminate()
            return self._send(200, {"ok": True})
        if self.path == "/reveal":
            p = str(body.get("path", ""))
            known = {t["video_path"] for t in (sample_templates() or [])}
            allowed = (os.path.realpath(SAMPLES), os.path.realpath(REPO / "opencut-exports"))
            if not p or not os.path.isfile(p) or not (p in known or any(os.path.realpath(p).startswith(a + os.sep) for a in allowed)):
                return self._send(400, {"error": "that file is not one of your samples"})
            subprocess.Popen([*REVEAL_CMD, p])
            return self._send(200, {"ok": True})
        if self.path == "/pipeline/start":
            leads = [l for l in (body.get("leads") or []) if isinstance(l, dict) and l.get("id") and YT_RE.match(str(l.get("url", "")))][:25]
            if not leads:
                return self._send(400, {"error": "no leads with a YouTube episode link"})
            with LOCK:
                if STATE["running"]:
                    return self._send(409, {"error": "a run is already in progress"})
                STATE.update(running=True, log=[f"[runner] preparing clips for {len(leads)} lead(s)"])
                threading.Thread(target=run_pipeline, args=(leads, float(body.get("minutes") or 5), int(body.get("clips") or 1),
                                 body.get("after"), clean(body.get("folder") or "", 80) or None), daemon=True).start()
            return self._send(200, {"ok": True, "leads": len(leads)})
        if self.path == "/emails/find":
            leads = [l for l in (body.get("leads") or []) if isinstance(l, dict) and l.get("id") and l.get("name")][:60]
            if not leads:
                return self._send(400, {"error": "no leads to search"})
            with LOCK:
                if STATE["running"]:
                    return self._send(409, {"error": "a run is already in progress"})
                STATE.update(running=True, log=[f"[runner] looking for public contact emails for {len(leads)} podcast(s)"])
                PIPE["stop"] = False
                threading.Thread(target=run_find_emails, args=(leads,), daemon=True).start()
            return self._send(200, {"ok": True, "leads": len(leads)})
        if self.path == "/email/preview":
            items = list(cold_email.plan(body.get("leads") or [], body.get("template") or {}, "preview", int(body.get("limit") or 20), True, int(body.get("step") or 0)))
            return self._send(200, {"items": items, "status": email_status()})
        if self.path == "/email/run":
            mode = body.get("mode")
            if mode not in ("drafts", "send"):
                return self._send(400, {"error": "mode must be drafts or send"})
            if mode == "send" and body.get("confirm") is not True:
                return self._send(400, {"error": "sending needs confirm: true"})
            st = email_status()
            if not st["ready"]:
                return self._send(400, {"error": "; ".join(st["problems"])})
            with LOCK:
                if STATE["running"]:
                    return self._send(409, {"error": "a run is already in progress"})
                STATE.update(running=True, log=[f"[runner] email run ({mode})"])
                threading.Thread(target=run_email, args=(body.get("leads") or [], body.get("template") or {}, mode, min(60, int(body.get("limit") or 20)),
                                 bool(body.get("ignore_window")), int(body.get("step") or 0)), daemon=True).start()
            return self._send(200, {"ok": True})
        if self.path == "/email/check-replies":
            try:
                res = cold_email.check_replies(body.get("sent") or [], log_fn=lambda m: None)
                res["found"] = [{k: v for k, v in f.items() if k != "text"} for f in auto_reply.handle(res.get("found") or [], log_fn=log)]
                b = cold_email.check_bounces(log_fn=lambda m: None)
                return self._send(200, {**res, "bounced": b["bounced"], "errors": (res.get("errors") or []) + b["errors"]})
            except Exception as e:
                return self._send(500, {"error": str(e)[:200]})
        if self.path == "/email/personalize":
            leads = [l for l in (body.get("leads") or []) if l.get("clipFile")]
            if not leads:
                return self._send(400, {"error": "no leads with a clip yet"})
            with LOCK:
                if STATE["running"]:
                    return self._send(409, {"error": "a run is already in progress"})
                STATE.update(running=True, log=[f"[runner] writing personal notes for {len(leads)} lead(s)"])
                PIPE["stop"] = False
                threading.Thread(target=run_personalize, args=(leads,), daemon=True).start()
            return self._send(200, {"ok": True, "leads": len(leads)})
        if self.path == "/clips/share":
            root = (REPO / "opencut-exports").resolve()
            names = []
            for f in body.get("files") or []:
                p = Path(str(f)).resolve()
                if root in p.parents and p.suffix.lower() == ".mp4" and p.exists():
                    names.append(p.name)
            if not names:
                return self._send(400, {"error": "no clip files found to share"})
            links, errors = [], []
            for k, n in enumerate(names):
                code, shared = app_call("/api/outreach/share-clip", {"id": f"opencut-exports/{n}", "name": f"{(body.get('name') or 'clip')} - clip {k + 1}"}, timeout=300)
                if code == 200 and shared.get("success"):
                    links.append(shared.get("link", ""))
                else:
                    errors.append(shared.get("error") or str(code))
            return self._send(200, {"links": links, "errors": errors})
        if self.path == "/personal/neutralize":
            out = {}
            for k, phrase in (body.get("phrases") or {}).items():
                out[k] = personalize.neutralize(str(phrase)[:300])
            return self._send(200, {"phrases": out})
        if self.path == "/unibox/yes":
            try:
                return self._send(200, auto_reply.preview(str(body.get("to") or ""), str(body.get("name") or ""), str(body.get("slug") or "")))
            except Exception as e:
                return self._send(500, {"error": str(e)[:200]})
        if self.path in ("/unibox/drafts", "/unibox/replies", "/unibox/draft/update", "/unibox/draft/delete", "/unibox/draft/send"):
            try:
                if self.path == "/unibox/drafts":
                    return self._send(200, cold_email.list_drafts(log_fn=lambda m: None))
                if self.path == "/unibox/replies":
                    return self._send(200, cold_email.list_replies(int(body.get("days") or 21)))
                mid = str(body.get("mid") or "")
                if self.path == "/unibox/draft/update":
                    return self._send(200, {"mid": cold_email.update_draft(mid, str(body.get("subject") or ""), str(body.get("body") or ""))})
                if self.path == "/unibox/draft/delete":
                    return self._send(200, {"ok": cold_email.discard_draft(mid)})
                return self._send(200, {"ok": cold_email.send_saved_reply(mid)})
            except Exception as e:
                return self._send(500, {"error": str(e)[:200]})
        if self.path == "/fit/run":
            leads = [{k: str(l.get(k) or "")[:300] for k in ("id", "name", "url", "web", "subs")} for l in (body.get("leads") or [])][:40]
            if not leads:
                return self._send(400, {"error": "no leads to check"})
            with LOCK:
                if STATE["running"]:
                    return self._send(409, {"error": "a run is already in progress"})
                import tempfile
                f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
                json.dump(leads, f)
                f.close()
                STATE.update(running=True, log=[f"[runner] checking {len(leads)} lead(s) with Google AI"])
                threading.Thread(target=run_fit, args=(f.name,), daemon=True).start()
            return self._send(200, {"ok": True})
        if self.path == "/awake":
            if "on" in body:
                return self._send(200, awake_set(bool(body.get("on")), body.get("minutes") or 180))
            return self._send(200, awake_status())
        if self.path == "/email/sent":
            cutoff = time.time() - 30 * 86400
            rows = [{k: e.get(k) for k in ("id", "to", "from", "ts", "step", "subject", "variant", "provider")} for e in cold_email.sent_entries() if e.get("ts", 0) > cutoff]
            return self._send(200, {"sent": rows})
        if self.path == "/notify":
            title = clean(body.get("title") or "Clipper CRM", 60)
            msg = clean(body.get("message") or "", 160)
            if sys.platform == "darwin" and msg:
                subprocess.run(["osascript", "-e", 'display notification "%s" with title "%s" sound name "Glass"' % (msg.replace('"', "'"), ("ClipperCRM: " + title).replace('"', "'"))],
                               capture_output=True, timeout=10)
            sent = False
            if body.get("phone", True) and msg:
                extra = (" " + REMOTE_HINT) if "needs you" in title.lower() else ""
                sent = phone_notify(title, msg + extra, key=str(body.get("key") or title), every=int(body.get("every") or 600))
            return self._send(200, {"ok": True, "phone": sent, "phone_configured": phone_ready()})
        if self.path == "/email/stats":
            return self._send(200, cold_email.stats())
        if self.path == "/pipeline/stop":
            PIPE["stop"] = True
            return self._send(200, {"ok": True})
        if self.path == "/clipper/send":
            url, start, end = str(body.get("url", "")).strip(), str(body.get("start", "")).strip(), str(body.get("end", "")).strip()
            name = clean(body.get("name") or "Outreach sample", 60) or "Outreach sample"
            folder = clean(body.get("folder") or "", 80) or None
            if not YT_RE.match(url) or not TIME_RE.match(start) or not TIME_RE.match(end):
                return self._send(400, {"error": "need a YouTube link and start/end like 12:00"})
            with LOCK:
                if STATE["running"]:
                    return self._send(409, {"error": "a run is already in progress"})
                STATE.update(running=True, log=[f"[runner] sending to clipper: {name}"])
                threading.Thread(target=run_send, args=(url, start, end, name, folder), daemon=True).start()
            return self._send(200, {"ok": True})
        if self.path != "/run":
            return self._send(404, {"error": "not found"})
        with LOCK:
            if STATE["running"]:
                return self._send(409, {"error": "a run is already in progress"})
            niches = [clean(x) for x in body.get("niches", []) if clean(x)][:15]
            if not niches:
                return self._send(400, {"error": "no niches"})
            argv = ["--count", str(max(1, min(25, int(body.get("count") or 10))))]
            focus = clean(body.get("focus", ""), 200)
            if focus:
                argv += ["--focus", focus]
            if body.get("dry"):
                argv.append("--dry-run")
            elif body.get("emit"):
                argv.append("--emit")
            argv += niches
            STATE.update(running=True, log=[f"[runner] starting: {' '.join(argv)}"])
            threading.Thread(target=run_job, args=(argv,), daemon=True).start()
        self._send(200, {"ok": True})


def keep_clipper_awake():
    """The clipper app shuts itself down after an hour with no open page. While this helper is running (and the app is up),
    ping it every 30 seconds so unattended runs are not cut off. Set KEEP_CLIPPER_ALIVE=0 to turn this off."""
    while True:
        time.sleep(30)
        try:
            urllib.request.urlopen(urllib.request.Request(APP_URL + "/api/heartbeat", data=b"{}", headers={"Content-Type": "application/json"}), timeout=5).read()
        except Exception:
            pass


if __name__ == "__main__":
    if os.getenv("KEEP_CLIPPER_ALIVE", "1") != "0":
        threading.Thread(target=keep_clipper_awake, daemon=True).start()
    load_env()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"Clipper runner listening on http://127.0.0.1:{PORT}  (leave this window open, Ctrl+C to stop)")
    if not (os.getenv("CRM_SYNC_URL") and os.getenv("CRM_SYNC_PASSWORD")):
        print("Note: CRM_SYNC_URL / CRM_SYNC_PASSWORD not set. Put them in tools/.env or runs will be preview only.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
