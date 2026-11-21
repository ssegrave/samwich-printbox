"""
PrintBox printer monitor - moves Print Jobs rows to Printing / Done / Failed.

Connects to each Bambu printer's local MQTT (port 8883, user "bblp", LAN access code) and
watches its report. Printers stay in cloud mode; this only reads status. The one message
it sends is the standard "pushall" status request, once per connection, because the P1
series otherwise reports only changed fields (never which file is printing).

Matching: Bambu Studio names the print after the sent file, e.g.
"20261121-074321_hacha_plate_1.gcode_plate_1" -> processed/20261121-074321_hacha_plate_1.json,
plate 1. Prints that didn't come through PrintBox have no .json and are ignored.

Per printer, the last (job, plate, state) acted on is kept in <INBOX>/printers.json so a
restart doesn't repeat an update. States: PREPARE/SLICING/RUNNING/PAUSE -> Printing,
FINISH -> plate done (row Done once every plate has finished), FAILED -> Failed.

Settings (.env): BAMBU_ACCESS_<serial>=<access code> per printer; optional
BAMBU_IP_<serial>=<ip> (otherwise found by the printers' network announcements).
Standard library only.
"""
import json
import logging
import os
import re
import socket
import ssl
import struct
import threading
import time
from datetime import datetime
from pathlib import Path

import notion

log = logging.getLogger("printbox")

ACTIVE = {"PREPARE", "SLICING", "RUNNING", "PAUSE"}
RECONNECT_SECONDS = 60
KEEPALIVE = 60


def configured_printers() -> dict[str, str]:
    """serial -> access code, from BAMBU_ACCESS_<serial> settings."""
    return {k[len("BAMBU_ACCESS_"):]: v for k, v in os.environ.items()
            if k.startswith("BAMBU_ACCESS_") and v}


# ------------------------------------------------------------- discovery ----

def discover(serials: set[str], timeout: float = 30) -> dict[str, tuple[str, str]]:
    """serial -> (ip, name) from the printers' SSDP NOTIFY broadcasts on UDP 2021."""
    found: dict[str, tuple[str, str]] = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("", 2021))
        s.settimeout(1)
        end = time.time() + timeout
        while time.time() < end and not serials <= found.keys():
            try:
                data, addr = s.recvfrom(4096)
            except socket.timeout:
                continue
            text = data.decode("utf-8", "replace")
            usn = re.search(r"USN:\s*(\S+)", text)
            name = re.search(r"DevName\.bambu\.com:\s*(.+)", text)
            if usn and usn.group(1) in serials:
                found[usn.group(1)] = (addr[0], name.group(1).strip() if name else usn.group(1))
    finally:
        s.close()
    return found


# ------------------------------------------------------------- mqtt ---------

def _str(s: str) -> bytes:
    b = s.encode()
    return struct.pack("!H", len(b)) + b


def _packet(ptype: int, body: bytes) -> bytes:
    n, rem = len(body), b""
    while True:
        byte, n = n % 128, n // 128
        rem += bytes([byte | (0x80 if n else 0)])
        if not n:
            return bytes([ptype]) + rem + body


def _recv_exact(sock, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("printer closed the connection")
        data += chunk
    return data


def _read_packet(sock) -> tuple[int, bytes]:
    ptype = _recv_exact(sock, 1)[0]
    mult, length = 1, 0
    while True:
        b = _recv_exact(sock, 1)[0]
        length += (b & 0x7F) * mult
        mult *= 128
        if not b & 0x80:
            break
    return ptype, _recv_exact(sock, length)


# ------------------------------------------------------------- matching -----

def parse_subtask(subtask: str, gcode_file: str | None) -> tuple[str, int | None]:
    """'20261121-074321_hacha_plate_1.gcode_plate_1' -> ('20261121-074321_hacha_plate_1', 1)."""
    m = re.fullmatch(r"(.+?)(?:\.gcode)?(?:\.3mf)?_plate_(\d+)", subtask)
    stem, plate = (m.group(1), int(m.group(2))) if m else (re.sub(r"(\.gcode)?(\.3mf)?$", "", subtask), None)
    if plate is None and gcode_file:
        g = re.search(r"plate_(\d+)\.gcode", gcode_file)
        plate = int(g.group(1)) if g else None
    return stem, plate


class Monitor:
    def __init__(self, processed: Path, state_file: Path):
        self.processed = processed
        self.state_file = state_file
        self.lock = threading.Lock()

    # persisted "last acted on" per printer
    def _load(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _already(self, serial: str, key: list) -> bool:
        return self._load().get(serial) == key

    def _remember(self, serial: str, key: list) -> None:
        state = self._load()
        state[serial] = key
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def handle(self, serial: str, printer: str, gcode_state: str, subtask: str,
               gcode_file: str | None) -> None:
        """Act on a (job, plate, state) the first time it's seen for this printer."""
        if not subtask or gcode_state not in ACTIVE | {"FINISH", "FAILED"}:
            return
        stem, plate = parse_subtask(subtask, gcode_file)
        phase = "printing" if gcode_state in ACTIVE else gcode_state.lower()
        key = [stem, plate, phase]
        with self.lock:
            if self._already(serial, key):
                return
            json_path = self.processed / f"{stem}.json"
            if not json_path.is_file():
                log.info("PRINTER %s: %s %s (not a PrintBox job, ignored)", printer, phase, subtask)
                self._remember(serial, key)
                return
            info = json.loads(json_path.read_text(encoding="utf-8"))
            self._apply(info, json_path, printer, plate, phase)
            self._remember(serial, key)

    def _apply(self, info: dict, json_path: Path, printer: str, plate: int | None, phase: str) -> None:
        now = datetime.now().astimezone()
        info.setdefault("prints", []).append(
            {"printer": printer, "plate": plate, "event": phase, "at": now.isoformat(timespec="seconds")})
        all_plates = {p["index"] for p in info["plates"] if p.get("has_gcode", True)}
        status, printed = None, None
        if phase == "printing":
            status = "Printing"
        elif phase == "failed":
            status = "Failed"
        elif phase == "finish":
            done = {e["plate"] for e in info["prints"] if e["event"] == "finish"}
            if plate is None or all_plates <= done:
                status, printed = "Done", now.date().isoformat()
            else:
                status = "Printing"   # more plates to go
        job = (info.get("notion") or {}).get("job_id") or info["name"]
        log.info("PRINTER %s: %s %s plate %s -> %s", printer, job, phase, plate, status)
        page_id = (info.get("notion") or {}).get("page_id")
        if page_id and notion.configured():
            try:
                notion.set_status(page_id, status, printed)
            except Exception as e:  # noqa: BLE001
                log.error("Notion: status update failed for %s: %s", job, e)
                info["prints"][-1]["notion_error"] = str(e)
        json_path.write_text(json.dumps(info, indent=2), encoding="utf-8")

    # ---- per-printer connection loop
    def run_printer(self, serial: str, code: str) -> None:
        ip_override = os.environ.get(f"BAMBU_IP_{serial}")
        name = serial
        while True:
            try:
                ip = ip_override
                if not ip:
                    found = discover({serial})
                    if serial not in found:
                        log.warning("PRINTER %s: not found on the network, retrying", serial[-4:])
                        time.sleep(RECONNECT_SECONDS)
                        continue
                    ip, name = found[serial]
                self._session(serial, name, ip, code)
            except Exception as e:  # noqa: BLE001
                log.warning("PRINTER %s: connection lost (%s: %s), reconnecting", name, type(e).__name__, e)
            time.sleep(RECONNECT_SECONDS)

    def _session(self, serial: str, name: str, ip: str, code: str) -> None:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE   # printers use a self-signed certificate on the LAN
        sock = ctx.wrap_socket(socket.create_connection((ip, 8883), timeout=15), server_hostname=ip)
        try:
            flags = 0x80 | 0x40 | 0x02   # username, password, clean session
            sock.sendall(_packet(0x10, _str("MQTT") + bytes([4, flags]) + struct.pack("!H", KEEPALIVE)
                                 + _str(f"printbox-{serial[-6:]}") + _str("bblp") + _str(code)))
            ptype, data = _read_packet(sock)
            if ptype >> 4 != 2 or len(data) < 2 or data[1] != 0:
                raise ConnectionError(f"login refused (code {data[1] if len(data) > 1 else '?'}) - "
                                      "check the access code")
            sock.sendall(_packet(0x82, struct.pack("!H", 1) + _str(f"device/{serial}/report") + b"\x00"))
            pushall = json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}).encode()
            sock.sendall(_packet(0x30, _str(f"device/{serial}/request") + pushall))
            log.info("PRINTER %s: connected (%s)", name, ip)
            sock.settimeout(KEEPALIVE / 2)
            current: dict = {}
            last_ping = time.time()
            while True:
                if time.time() - last_ping > KEEPALIVE / 2:
                    sock.sendall(_packet(0xC0, b""))
                    last_ping = time.time()
                try:
                    ptype, data = _read_packet(sock)
                except socket.timeout:
                    continue
                if ptype >> 4 != 3:
                    continue
                tlen = struct.unpack("!H", data[:2])[0]
                payload = data[2 + tlen + (2 if (ptype >> 1) & 3 else 0):]
                try:
                    report = json.loads(payload).get("print") or {}
                except ValueError:
                    continue
                for k in ("gcode_state", "subtask_name", "gcode_file"):
                    if k in report:
                        current[k] = report[k]
                if "gcode_state" in report or "subtask_name" in report:
                    self.handle(serial, name, current.get("gcode_state", ""),
                                current.get("subtask_name", ""), current.get("gcode_file"))
        finally:
            sock.close()


def start(processed: Path, state_file: Path) -> list[threading.Thread]:
    """Start one daemon thread per configured printer; returns them (empty if none)."""
    printers = configured_printers()
    monitor = Monitor(processed, state_file)
    threads = []
    for serial, code in printers.items():
        t = threading.Thread(target=monitor.run_printer, args=(serial, code),
                             name=f"printer-{serial[-4:]}", daemon=True)
        t.start()
        threads.append(t)
    if threads:
        log.info("Printer monitor: watching %d printer(s)", len(threads))
    return threads
