#!/usr/bin/env python3
"""
PrintBox opener - the "Open" link in Notion Print Jobs.

Serves http://localhost:8765/open/PRINT-N on this PC. A request finds the job's .json in
processed/ (matched by its Notion Job ID) and launches the right slicer with the synced
.gcode.3mf. Printing itself stays manual: confirm AMS mapping in the slicer, then Print.

Slicer choice: H3C jobs -> Bambu Studio (OrcaSlicer doesn't support the H3C yet);
otherwise the slicer that made the file. Add ?slicer=bambu or ?slicer=orca to override.

Run on every PC that should open jobs (unlike the watcher, which runs on one machine).
Settings come from the environment, then the repo's .env:
  INBOX_DIR, OPENER_PORT (8765), BAMBU_STUDIO_EXE, ORCASLICER_EXE.
Standard library only.
"""
import html
import json
import logging
import os
import re
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from watcher import INBOX, PROCESSED  # also loads .env

PORT = int(os.environ.get("OPENER_PORT", "8765"))

SLICERS = {
    "bambu": ("Bambu Studio", "BAMBU_STUDIO_EXE", [
        r"C:\Program Files\Bambu Studio\bambu-studio.exe",
    ]),
    "orca": ("OrcaSlicer", "ORCASLICER_EXE", [
        r"C:\Program Files\OrcaSlicer\orca-slicer.exe",
        str(Path.home() / r"AppData\Local\Programs\OrcaSlicer\orca-slicer.exe"),
    ]),
}
BAMBU_ONLY_PRINTERS = {"Bambu Lab H3C"}

log = logging.getLogger("printbox.opener")


def find_exe(key: str) -> Path | None:
    _, env_var, defaults = SLICERS[key]
    for candidate in [os.environ.get(env_var, "")] + defaults:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def find_job(job_id: str) -> dict | None:
    for json_path in sorted(PROCESSED.glob("*.json"), reverse=True):
        try:
            info = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (info.get("notion") or {}).get("job_id") == job_id:
            return info
    return None


def choose_slicer(info: dict, override: str | None) -> str:
    if info.get("printer_model") in BAMBU_ONLY_PRINTERS:
        return "bambu"
    if override in SLICERS:
        return override
    return "orca" if (info.get("slicer") or "").lower().startswith("orcaslicer") else "bambu"


def open_job(job_id: str, override: str | None) -> tuple[int, str]:
    """Launch the slicer; returns (HTTP status, message)."""
    info = find_job(job_id)
    if not info:
        return 404, (f"No job {job_id} in {PROCESSED}. If it was just added, "
                     "Google Drive may still be syncing - try again in a moment.")
    file = INBOX / info["processed_file"]
    if not file.is_file():
        return 404, f"{job_id} ({info['name']}): file not found at {file}"
    key = choose_slicer(info, override)
    name = SLICERS[key][0]
    exe = find_exe(key)
    if not exe:
        return 500, (f"{name} isn't installed on this PC (or set {SLICERS[key][1]} in .env "
                     "to its .exe path).")
    subprocess.Popen([str(exe), str(file)], close_fds=True)
    log.info("OPEN %s (%s) in %s", job_id, info["name"], name)
    return 200, f"Opening {job_id} - {info['name']} in {name}. Check AMS mapping, then Print."


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>PrintBox {job}</title>
<style>body{{font:16px system-ui,sans-serif;max-width:40em;margin:3em auto;padding:0 1em}}
.ok{{color:#1a7f37}}.err{{color:#b42318}}a{{margin-right:1em}}</style></head><body>
<h2 class="{cls}">{msg}</h2><p>{links}</p><p><small>{note}</small></p>
{script}</body></html>"""

# Browsers only let a page close its own tab if that tab has no history (a fresh tab from a
# link, e.g. Notion's Open). location.replace() keeps it that way for the override links.
CLOSE_SCRIPT = "<script>setTimeout(function(){window.close()}, 1500)</script>"


class Server(ThreadingHTTPServer):
    """No address reuse: on Windows SO_REUSEADDR lets a second opener share the port."""
    allow_reuse_address = False

    def server_bind(self) -> None:
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        url = urlparse(self.path)
        m = re.fullmatch(r"/open/([A-Za-z]+-\d+)", url.path)
        if not m:
            self.send_error(404)
            return
        job_id = m.group(1).upper()
        override = (parse_qs(url.query).get("slicer") or [None])[0]
        try:
            status, msg = open_job(job_id, override)
        except Exception as e:  # noqa: BLE001
            log.exception("open %s failed", job_id)
            status, msg = 500, f"Error opening {job_id}: {e}"
        links = " ".join(f'<a href="/open/{job_id}?slicer={k}" '
                         f'onclick="location.replace(this.href);return false">Open in {v[0]} instead</a>'
                         for k, v in SLICERS.items())
        ok = status == 200
        body = PAGE.format(job=job_id, cls="ok" if ok else "err", msg=html.escape(msg), links=links,
                           note="This tab closes itself; close it if it doesn't." if ok
                           else "You can close this tab.",
                           script=CLOSE_SCRIPT if ok else "").encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        log.debug("%s " + fmt, self.address_string(), *args)


def main() -> None:
    # Per-PC log (the opener runs on every PC, so not in the shared Drive folder).
    log_file = Path(os.environ.get("OPENER_LOG") or
                    Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "PrintBox" / "opener.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")]
    if sys.stdout:  # None under pythonw (background mode)
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    for key, (name, env_var, _) in SLICERS.items():
        exe = find_exe(key)
        log.info("%s: %s", name, exe or f"not found (set {env_var} in .env)")
    try:
        server = Server(("127.0.0.1", PORT), Handler)
    except OSError as e:
        log.error("Can't listen on port %d (%s) - is the opener already running?", PORT, e)
        sys.exit(1)
    log.info("Opener on http://localhost:%d/open/PRINT-N (jobs in %s)", PORT, PROCESSED)
    server.serve_forever()


if __name__ == "__main__":
    main()
