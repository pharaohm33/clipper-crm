#!/usr/bin/env python3
"""
Local helper so the website's "Run live" button can start google_ai_to_crm.py on your computer.

Start it once and leave the window open:
    cd ~/clipper-crm && python3 tools/local_runner.py

It only listens on 127.0.0.1 and only accepts requests from this site (or localhost). Your keys live in
tools/.env (copy tools/.env.example) and are never sent to the browser.
"""
import json, os, re, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
SCRIPT = os.getenv("RUNNER_SCRIPT", str(HERE / "google_ai_to_crm.py"))
PORT = int(os.getenv("RUNNER_PORT", "8765"))
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
