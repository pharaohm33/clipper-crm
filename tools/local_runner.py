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
SCRIPT = os.getenv("RUNNER_SCRIPT", str(HERE / "google_ai_to_crm.py"))
PORT = int(os.getenv("RUNNER_PORT", "8765"))
APP_URL = os.getenv("CLIPPER_URL", "http://127.0.0.1:5001").rstrip("/")
GRAB = os.getenv("GRAB_SCRIPT", str(HERE / "grab_sample.sh"))
SAMPLES = os.getenv("SAMPLES_DIR", str(Path.home() / "Downloads" / "clip-samples"))
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
        proc.wait()
        STATE["log"].append(f"[runner] finished (exit {proc.returncode})")
    except Exception as e:
        STATE["log"].append(f"[runner] failed to start: {e}")
    finally:
        STATE["running"] = False


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


def clipper_status():
    code, d = app_call("/api/clipper/status", timeout=2)
    if code != 200:
        return {"state": "off", "url": APP_URL}
    return {"state": "busy" if d.get("running") else "on", "stage": d.get("stage"), "message": d.get("message"),
            "pct": d.get("pct"), "error": d.get("error"), "template_slug": d.get("template_slug"), "url": APP_URL}


YT_RE = re.compile(r"^https://((www|m)\.)?(youtube\.com|youtu\.be)/\S+$")
TIME_RE = re.compile(r"^\d{1,2}(:\d{2}){1,2}$")


def log(msg):
    STATE["log"].append(msg)


def run_send(url, start, end, name):
    """Download a slice of a YouTube video, then save it as a NEW template in the clipper (no clips are generated:
    you change the rules there and press Generate yourself)."""
    try:
        log(f"[runner] downloading {start} to {end} ...")
        env = {**os.environ, "NO_OPEN": "1"}
        p = subprocess.run(["bash", GRAB, url, start, end, SAMPLES], capture_output=True, text=True, env=env, timeout=1800)
        saved = [l[6:].strip() for l in p.stdout.splitlines() if l.startswith("Saved: ")]
        if p.returncode != 0 or not saved:
            log("[runner] download failed. " + (p.stderr.strip().splitlines() or ["yt-dlp gave no details"])[-1])
            return
        video = saved[-1]
        log(f"[runner] saved {video}")
        waited, announced = 0, False
        while True:
            st = clipper_status()
            if st["state"] == "off":
                log(f"[runner] the clipper app is off ({APP_URL}). The clip source is saved here, start the app and click again:\n   {video}")
                return
            if st["state"] == "on":
                code, resp = app_call("/api/clip-templates/create", {"name": name, "path": video, "folder": "Outreach samples"}, timeout=30)
                if code == 200 and resp.get("success"):
                    break
                if code != 409:
                    log(f"[runner] clipper rejected the template: {resp.get('error') or code}")
                    return
            if waited >= 900:
                log("[runner] clipper stayed busy for 15 minutes, giving up. The file is saved:\n   " + video)
                return
            if not announced or waited % 60 == 0:
                log(f"[runner] clipper is busy ({st.get('message') or 'working'}), waiting for it to finish ...")
                announced = True
            time.sleep(10)
            waited += 10
        log("[runner] template is being created (transcribing the 5 minutes) ...")
        last = ""
        for _ in range(600):
            time.sleep(3)
            st = clipper_status()
            if st["state"] == "off":
                log("[runner] lost contact with the clipper app.")
                return
            if st.get("message") and st["message"] != last:
                last = st["message"]
                log(f"   clipper: {last}")
            if st["state"] == "on":
                break
        st = clipper_status()
        if st.get("error"):
            log(f"[runner] the clipper reported an error: {st['error']}")
            return
        log(f"[runner] DONE. Template \"{name}\" is in the clipper (folder: Outreach samples). Open it, adjust the rules, then press Generate.")
    except Exception as e:
        log(f"[runner] failed: {e}")
    finally:
        STATE["running"] = False


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
            self._send(200, {"ok": True, "running": STATE["running"], "lines": len(STATE["log"]),
                             "configured": bool(os.getenv("CRM_SYNC_URL") and os.getenv("CRM_SYNC_PASSWORD")),
                             "yt": bool(os.getenv("YT_API_KEY"))})
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
        if self.path == "/clipper/send":
            url, start, end = str(body.get("url", "")).strip(), str(body.get("start", "")).strip(), str(body.get("end", "")).strip()
            name = clean(body.get("name") or "Outreach sample", 60) or "Outreach sample"
            if not YT_RE.match(url) or not TIME_RE.match(start) or not TIME_RE.match(end):
                return self._send(400, {"error": "need a YouTube link and start/end like 12:00"})
            with LOCK:
                if STATE["running"]:
                    return self._send(409, {"error": "a run is already in progress"})
                STATE.update(running=True, log=[f"[runner] sending to clipper: {name}"])
                threading.Thread(target=run_send, args=(url, start, end, name), daemon=True).start()
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
            argv += niches
            STATE.update(running=True, log=[f"[runner] starting: {' '.join(argv)}"])
            threading.Thread(target=run_job, args=(argv,), daemon=True).start()
        self._send(200, {"ok": True})


if __name__ == "__main__":
    load_env()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"Clipper runner listening on http://127.0.0.1:{PORT}  (leave this window open, Ctrl+C to stop)")
    if not (os.getenv("CRM_SYNC_URL") and os.getenv("CRM_SYNC_PASSWORD")):
        print("Note: CRM_SYNC_URL / CRM_SYNC_PASSWORD not set. Put them in tools/.env or runs will be preview only.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
