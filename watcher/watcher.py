#!/usr/bin/env python3
"""
PrintBox watcher - Phase 1 (parse only).

Watches a drop folder (default: ~/Documents/PrintBox, or INBOX_DIR) for sliced Bambu Studio / OrcaSlicer files (.gcode.3mf),
waits until each file has finished copying, reads the slicer metadata inside it,
and files it:

  processed/<timestamp>_<name>.gcode.3mf   the original file
  processed/<timestamp>_<name>.json        everything parsed from it
  processed/<timestamp>_<name>.plateN.png  plate preview image(s)
  failed/<timestamp>_<name>...             + .error.txt explaining why

Later phases plug in at handle_job(): SimplyPrint upload/queue, then Notion.
Standard library only.
"""
import json
import logging
import os
import re
import shutil
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

INBOX = Path(os.environ.get("INBOX_DIR") or (Path.home() / "Documents" / "PrintBox")).expanduser()
PROCESSED = INBOX / "processed"
FAILED = INBOX / "failed"
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "3"))
STABLE_CHECKS = int(os.environ.get("STABLE_CHECKS", "2"))   # unchanged polls before processing
BAD_ZIP_GRACE = float(os.environ.get("BAD_ZIP_GRACE_SECONDS", "120"))

log = logging.getLogger("printbox")


# ---------------------------------------------------------------- parsing ----

def job_name(path: Path) -> str:
    name = path.name
    for suffix in (".gcode.3mf", ".3mf"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def fmt_duration(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _num(value, cast=float, default=None):
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def _scalar(value):
    """project_settings values are sometimes 1-item lists."""
    if isinstance(value, list) and len(value) == 1:
        return value[0]
    return value


def read_application(z: zipfile.ZipFile, names: set) -> str | None:
    """Slicer name+version from 3D/3dmodel.model.

    OrcaSlicer writes Application="BambuStudio-<ver>" for compatibility and adds its own
    <metadata name="OrcaSlicer">2.5.1</metadata>, so check for that first.
    """
    if "3D/3dmodel.model" not in names:
        return None
    with z.open("3D/3dmodel.model") as f:
        head = f.read(65536).decode("utf-8", "replace")
    m = re.search(r'<metadata name="OrcaSlicer">([^<]*)</metadata>', head)
    if m:
        return f"OrcaSlicer-{m.group(1).strip()}"
    m = re.search(r'<metadata name="Application">([^<]*)</metadata>', head)
    return m.group(1).strip() if m else None


def parse_3mf(path: Path) -> dict:
    """Read Metadata/slice_info.config (+ project_settings.config) from a sliced 3MF."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if "Metadata/slice_info.config" not in names:
            raise ValueError(
                "No Metadata/slice_info.config - this is an unsliced project file. "
                "In the slicer use File > Export > 'Export plate sliced file' (.gcode.3mf)."
            )

        root = ET.fromstring(z.read("Metadata/slice_info.config"))
        header = {h.get("key"): h.get("value") for h in root.iter("header_item")}

        settings = {}
        if "Metadata/project_settings.config" in names:
            try:
                settings = json.loads(z.read("Metadata/project_settings.config"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                log.warning("project_settings.config present but not readable JSON")

        plates = []
        for plate in root.findall("plate"):
            md = {m.get("key"): m.get("value") for m in plate.findall("metadata")}
            idx = _num(md.get("index"), int, len(plates) + 1)
            filaments = [
                {
                    "slot": _num(f.get("id"), int),
                    "type": f.get("type"),
                    "color": f.get("color"),
                    "used_g": _num(f.get("used_g")),
                    "used_m": _num(f.get("used_m")),
                    "profile_id": f.get("tray_info_idx"),
                }
                for f in plate.findall("filament")
            ]
            prediction = _num(md.get("prediction"), int, 0)
            plates.append(
                {
                    "index": idx,
                    "print_time_s": prediction,
                    "print_time": fmt_duration(prediction),
                    "weight_g": _num(md.get("weight")),
                    "printer_model_id": md.get("printer_model_id"),
                    "nozzle_diameters": md.get("nozzle_diameters"),
                    "support_used": md.get("support_used"),
                    "filaments": filaments,
                    "warnings": [w.attrib for w in plate.findall("warning")],
                    "has_gcode": f"Metadata/plate_{idx}.gcode" in names,
                    "thumbnail_member": (
                        f"Metadata/plate_{idx}.png" if f"Metadata/plate_{idx}.png" in names else None
                    ),
                }
            )

        if not plates:
            raise ValueError("slice_info.config has no <plate> entries - nothing was sliced.")
        if not any(p["has_gcode"] for p in plates):
            raise ValueError(
                "No Metadata/plate_N.gcode inside - this is an unsliced project file. "
                "In the slicer use File > Export > 'Export plate sliced file' (.gcode.3mf)."
            )

        return {
            "name": job_name(path),
            "source_file": path.name,
            "size_bytes": path.stat().st_size,
            "slicer": read_application(z, names),   # e.g. "BambuStudio-02.03.01.51" / "OrcaSlicer-2.3.1"
            "slicer_version": header.get("OrcaSlicer-Version") or header.get("X-BBL-Client-Version"),
            "printer_model": _scalar(settings.get("printer_model")),
            "printer_variant": _scalar(settings.get("printer_variant")),
            "printer_settings_id": _scalar(settings.get("printer_settings_id")),
            "plate_count": len(plates),
            "total_print_time_s": sum(p["print_time_s"] for p in plates),
            "total_print_time": fmt_duration(sum(p["print_time_s"] for p in plates)),
            "total_weight_g": round(sum(p["weight_g"] or 0 for p in plates), 2),
            "materials": sorted({f["type"] for p in plates for f in p["filaments"] if f["type"]}),
            "plates": plates,
        }


def extract_thumbnails(path: Path, info: dict, dest_stem: Path) -> list[str]:
    saved = []
    with zipfile.ZipFile(path) as z:
        for p in info["plates"]:
            member = p.get("thumbnail_member")
            if member:
                out = dest_stem.with_name(f"{dest_stem.name}.plate{p['index']}.png")
                out.write_bytes(z.read(member))
                saved.append(out.name)
    return saved


# ------------------------------------------------------------- pipeline -----

def handle_job(path: Path, info: dict) -> None:
    """Phase 1: nothing beyond parsing. Phase 2 (SimplyPrint) and 3 (Notion) go here."""
    plates = ", ".join(
        f"plate {p['index']}: {p['print_time']} / {p['weight_g']} g" for p in info["plates"]
    )
    log.info(
        "PARSED %s | %s | printer=%r (%s) | %s | materials=%s",
        info["name"], info["slicer"] or info["slicer_version"],
        info["printer_model"], info["printer_variant"], plates, ",".join(info["materials"]),
    )


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def file_success(path: Path, info: dict) -> None:
    PROCESSED.mkdir(exist_ok=True)
    dest_stem = PROCESSED / f"{stamp()}_{info['name']}"
    info["thumbnails"] = extract_thumbnails(path, info, dest_stem)
    info["processed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    dest_stem.with_name(dest_stem.name + ".json").write_text(json.dumps(info, indent=2))
    shutil.move(str(path), str(dest_stem.with_name(dest_stem.name + "".join(_suffixes(path)))))
    log.info("-> processed/%s", dest_stem.name)


def file_failure(path: Path, reason: str) -> None:
    FAILED.mkdir(exist_ok=True)
    dest = FAILED / f"{stamp()}_{path.name}"
    shutil.move(str(path), str(dest))
    dest.with_name(dest.name + ".error.txt").write_text(reason + "\n")
    log.error("FAILED %s: %s -> failed/%s", path.name, reason, dest.name)


def _suffixes(path: Path) -> str:
    return ".gcode.3mf" if path.name.lower().endswith(".gcode.3mf") else path.suffix


def is_candidate(p: Path) -> bool:
    n = p.name
    return (
        p.is_file()
        and n.lower().endswith(".3mf")
        and not n.startswith((".", "~$"))
    )


def main() -> None:
    for d in (INBOX, PROCESSED, FAILED):
        d.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(INBOX / "printbox.log", encoding="utf-8")]
    if sys.stdout:  # None under pythonw (background mode)
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )
    log.info("Watching %s (poll %ss, %s stable checks)", INBOX, POLL_SECONDS, STABLE_CHECKS)

    seen: dict[Path, tuple[int, float, int, float]] = {}  # path -> (size, mtime, stable_count, first_seen)
    while True:
        try:
            current = {p for p in INBOX.iterdir() if is_candidate(p)}
            for gone in set(seen) - current:
                seen.pop(gone, None)

            for p in sorted(current):
                try:
                    st = p.stat()
                except FileNotFoundError:
                    continue
                size, mtime = st.st_size, st.st_mtime
                prev = seen.get(p)
                if prev and prev[0] == size and prev[1] == mtime:
                    stable, first = prev[2] + 1, prev[3]
                else:
                    stable, first = 0, prev[3] if prev else time.time()
                seen[p] = (size, mtime, stable, first)
                if size == 0 or stable < STABLE_CHECKS:
                    continue

                try:
                    info = parse_3mf(p)
                except PermissionError:
                    continue  # Windows: slicer still has the file open; retry next poll
                except zipfile.BadZipFile:
                    if time.time() - first < BAD_ZIP_GRACE:
                        continue  # probably still copying; check again next poll
                    file_failure(p, "Not a valid 3MF/zip archive.")
                    seen.pop(p, None)
                    continue
                except Exception as e:  # noqa: BLE001
                    file_failure(p, f"{type(e).__name__}: {e}")
                    seen.pop(p, None)
                    continue

                try:
                    handle_job(p, info)
                    file_success(p, info)
                except PermissionError:
                    continue  # file locked mid-move; retry next poll
                except Exception as e:  # noqa: BLE001
                    log.exception("Pipeline error")
                    try:
                        file_failure(p, f"{type(e).__name__}: {e}")
                    except OSError:
                        log.exception("Could not move %s to failed/", p.name)
                seen.pop(p, None)
        except Exception:  # noqa: BLE001
            log.exception("Watcher loop error")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
