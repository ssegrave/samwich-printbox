# CLAUDE.md - samwich-printinbox

Print-job inbox for The Samwich Shop (Samuel's maker operation). Read `docs/PLAN.md` for
the full decision log and phase checklist before changing anything.

## What it does
Slice in Bambu Studio / OrcaSlicer -> export plate sliced file (`.gcode.3mf`) into Google
Drive `My Drive\PrintInbox` (Windows: `G:\My Drive\PrintInbox`) -> `watcher/watcher.py`
parses it -> (Phase 2) creates a row in the Notion **Print Jobs** database -> an Open link
launches the right slicer locally, where Samuel confirms AMS mapping and prints.

## Hard constraints
- Printers stay in **cloud mode** (no LAN-only / Developer Mode) so Bambu Handy keeps
  working. Never automate print start; the human always hits Print in the slicer.
- **Only one machine runs the watcher** (the "processor"). Others just sync via Drive.
- H3C ("Mordecai") isn't supported in OrcaSlicer -> H3C jobs open in Bambu Studio.
- Bambu Studio's `bambustudio://open?file=` only accepts makerworld.com URLs.
- `watcher.py` is standard-library only and must run unchanged on Windows and Linux/Pi.
- Secrets (Notion token) live in `.env`, never committed. See `.env.example`.
- Keep the repo outside OneDrive/Google Drive folders (Windows: `$HOME\repos`).

## Machines
- samdesk (Windows 11) and Samuel's laptop (Windows): Python 3.10+ via `py`, Git for Windows.
- Future: Raspberry Pi as processor (rclone-synced Drive folder, `docker/`).

## Working style (Samuel's preferences)
- Step-by-step, with an explicit checkpoint after each step; build incrementally from a
  working baseline.
- Check official docs (Bambu wiki, Notion API, Google Drive help) rather than guessing.
- Commit in small, descriptive commits; push to `origin main`.

## Status
- Phase 1 (parse) built. Checkpoint 3 test a (Bambu Studio, P1S) passed:
  `printer_model='Bambu Lab P1S'`, slicer `BambuStudio-02.09.01.70`.
- Pending: tests b (Bambu Studio H3C - record exact printer_model), c (OrcaSlicer P1S),
  d (multi-plate), unsliced -> failed/. Then Phase 2 (Notion + opener).
- Notion Print Jobs DB: https://app.notion.com/p/41eda0e940bf81bc85ebcff87fda6ecf
  (needs internal integration "PrintInbox" connected; token goes in `.env`).
