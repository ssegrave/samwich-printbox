"""
PrintBox -> Notion Print Jobs (Phase 2).

Creates one row per parsed job in the Print Jobs database, using Notion API version
2025-09-03 (rows are created under the database's data source). Standard library only.

Needs NOTION_TOKEN and NOTION_DATABASE_ID (from the environment or the repo's .env).
"""
import colorsys
import json
import logging
import os
import urllib.error
import urllib.request

API = "https://api.notion.com/v1/"
NOTION_VERSION = "2025-09-03"

log = logging.getLogger("printbox")

PRINTERS = {"Bambu Lab P1S": "P1S", "Bambu Lab H3C": "Mordecai (H3C)"}

# Approximate color names for the "Colors" multi-select -> Notion option color.
COLOR_OPTIONS = {
    "White": "default", "Black": "default", "Gray": "gray", "Beige": "brown",
    "Brown": "brown", "Red": "red", "Orange": "orange", "Yellow": "yellow",
    "Green": "green", "Teal": "blue", "Blue": "blue", "Purple": "purple", "Pink": "pink",
}

# Properties PrintBox adds to Print Jobs if they're missing.
EXTRA_PROPERTIES = {
    "Filaments": {"rich_text": {}},
    "Colors": {"multi_select": {"options": [{"name": n, "color": c} for n, c in COLOR_OPTIONS.items()]}},
}


class NotionError(Exception):
    pass


def configured() -> bool:
    token = os.environ.get("NOTION_TOKEN", "")
    return bool(token) and not token.startswith("ntn_xxx") and bool(os.environ.get("NOTION_DATABASE_ID"))


def _request(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": "Bearer " + os.environ["NOTION_TOKEN"],
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("message", detail)
        except ValueError:
            pass
        raise NotionError(f"{method} {path}: HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise NotionError(f"{method} {path}: {e.reason}") from None


# ------------------------------------------------------------- colors -------

def color_name(hex_color: str | None) -> str | None:
    """Nearest plain color name for a slicer color like '#F99963' (alpha ignored)."""
    h = (hex_color or "").lstrip("#")
    if len(h) not in (6, 8):
        return None
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    hue *= 360
    if light >= 0.92:
        return "White"
    if light <= 0.12:
        return "Black"
    if sat < 0.15 or (sat < 0.25 and 0.2 < light < 0.8):
        return "White" if light > 0.85 else "Gray"
    if hue < 15 or hue >= 345:
        return "Pink" if light > 0.6 else "Red"
    if hue < 45:
        if light < 0.35:
            return "Brown"
        return "Beige" if light > 0.75 and sat < 0.6 else "Orange"
    if hue < 70:
        return "Brown" if light < 0.3 else "Yellow"
    if hue < 165:
        return "Green"
    if hue < 190:
        return "Teal"
    if hue < 250:
        return "Blue"
    if hue < 290:
        return "Purple"
    return "Pink"


def filament_slots(info: dict) -> list[dict]:
    """One entry per slot/type/color, with grams summed across plates."""
    slots: dict[tuple, dict] = {}
    for p in info["plates"]:
        for f in p["filaments"]:
            key = (f["slot"], f["type"], (f["color"] or "").upper())
            s = slots.setdefault(key, {"slot": f["slot"], "type": f["type"],
                                       "color": key[2], "used_g": 0.0})
            s["used_g"] += f["used_g"] or 0
    return sorted(slots.values(), key=lambda s: (s["slot"] is None, s["slot"] or 0))


def filaments_text(slots: list[dict]) -> str:
    lines = []
    for s in slots:
        name = color_name(s["color"])
        color = f"{name} ({s['color']})" if name else (s["color"] or "")
        lines.append(f"{s['slot']}: {s['type'] or '?'} {color} {round(s['used_g'], 2)} g".replace("  ", " "))
    return "\n".join(lines)


# ------------------------------------------------------------- rows ---------

def _text(value: str) -> dict:
    return {"rich_text": [{"text": {"content": value[:2000]}}]} if value else {"rich_text": []}


def _slicer(info: dict) -> str | None:
    s = (info.get("slicer") or "").lower()
    if s.startswith("orcaslicer"):
        return "OrcaSlicer"
    if s.startswith("bambustudio"):
        return "Bambu Studio"
    return None


def build_properties(info: dict, file_rel: str) -> dict:
    slots = filament_slots(info)
    colors = sorted({c for c in (color_name(s["color"]) for s in slots) if c})
    props = {
        "Name": {"title": [{"text": {"content": info["name"][:2000]}}]},
        "Status": {"status": {"name": "Inbox"}},
        "Printer": {"select": {"name": PRINTERS.get(info.get("printer_model") or "", "Other")}},
        "Est. Minutes": {"number": round(info["total_print_time_s"] / 60)},
        "Filament (g)": {"number": info["total_weight_g"]},
        "Plates": {"number": info["plate_count"]},
        "Materials": {"multi_select": [{"name": m} for m in info["materials"]]},
        "Filaments": _text(filaments_text(slots)),
        "Colors": {"multi_select": [{"name": c} for c in colors]},
        "File": _text(file_rel),
    }
    slicer = _slicer(info)
    if slicer:
        props["Slicer"] = {"select": {"name": slicer}}
    return props


_data_source_id: str | None = None


def data_source_id() -> str:
    """Resolve the database's data source once, adding PrintBox's extra properties if missing."""
    global _data_source_id
    if _data_source_id:
        return _data_source_id
    db = _request("GET", "databases/" + os.environ["NOTION_DATABASE_ID"])
    sources = db.get("data_sources") or []
    if not sources:
        raise NotionError("Print Jobs database has no data source (is the integration connected?)")
    ds_id = sources[0]["id"]
    existing = _request("GET", "data_sources/" + ds_id)["properties"]
    missing = {k: v for k, v in EXTRA_PROPERTIES.items() if k not in existing}
    if missing:
        _request("PATCH", "data_sources/" + ds_id, {"properties": missing})
        log.info("Notion: added properties %s to Print Jobs", ", ".join(missing))
    _data_source_id = ds_id
    return ds_id


def create_job(info: dict, file_rel: str) -> dict:
    """Create the Print Jobs row, then set its Open link from the assigned Job ID."""
    page = _request("POST", "pages", {
        "parent": {"type": "data_source_id", "data_source_id": data_source_id()},
        "properties": build_properties(info, file_rel),
    })
    uid = page.get("properties", {}).get("Job ID", {}).get("unique_id") or {}
    job_id = f"{uid['prefix']}-{uid['number']}" if uid.get("number") is not None else None
    if job_id:
        open_url = os.environ.get("OPEN_URL_BASE", "http://localhost:8765/open/") + job_id
        _request("PATCH", "pages/" + page["id"], {"properties": {"Open": {"url": open_url}}})
    return {"page_id": page["id"], "url": page.get("url"), "job_id": job_id}
