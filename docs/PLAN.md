# Plan & decisions

## Decisions (Nov 2026)
- **Local-first:** run on samdesk (Windows 11) now; move the watcher to a Raspberry Pi later.
  The old Ubuntu server laptop was overheating and is out of the loop.
- **Storage:** Google Drive for desktop, folder `My Drive\PrintInbox` (available offline).
  Code lives in GitHub, files live in Drive.
- **One processor:** only one machine runs the watcher (creates Notion rows, moves files).
  Every PC can run the opener.
- **Queue lives in Notion** (Print Jobs database under the 3D Printing page). No SimplyPrint
  automation, so no Print Farm plan needed.
- **No Developer Mode:** printers stay in cloud mode so Bambu Handy keeps working.
  Bambu's Authorization Control means third-party software can't start prints in cloud mode,
  so the final step is always human: open in slicer -> confirm AMS mapping -> Print.
- **H3C** isn't supported in OrcaSlicer yet -> H3C jobs open in Bambu Studio.
- Bambu Studio's `bambustudio://open?file=` links only accept makerworld.com; OrcaSlicer's
  accept self-hosted URLs. With the opener running locally, the slicer is launched directly.

## Phases
- [x] **Phase 1 - parse:** watch inbox, read `Metadata/slice_info.config` +
      `project_settings.config`, write `processed/<stamp>_<name>.json` + plate PNGs;
      unsliced/corrupt files -> `failed/` with `.error.txt`.
- [x] **Checkpoint 3:** real exports (Bambu Studio P1S, Bambu Studio H3C, OrcaSlicer P1S,
      multi-plate) parsed correctly; record exact `printer_model` strings.
      - `printer_model`: P1S = `Bambu Lab P1S` (model id `C12`), H3C = `Bambu Lab H3C` (`N10`).
      - OrcaSlicer (2.5.1) writes `Application=BambuStudio-<ver>`; it's identified by
        `<metadata name="OrcaSlicer">` in `3dmodel.model` / `OrcaSlicer-Version` header.
      - Unsliced Bambu project files *do* have slice_info plates, just no `plate_N.gcode`.
- [ ] **Phase 2 - Notion + opener:** create Print Jobs row per file (name, printer, time,
      grams, materials, plates, slicer, preview, Open link); local page at
      `http://localhost:8765/open/PRINT-N` launches the right slicer with the synced file.
- [ ] **Phase 3 - background + install:** run hidden at login (Task Scheduler), one-command
      installer for new PCs.
- [ ] **Phase 4 - Pi:** watcher on Pi with rclone-synced Drive folder; PCs run opener only.

## Notion
- Print Jobs database: https://app.notion.com/p/41eda0e940bf81bc85ebcff87fda6ecf
- Integration: internal "PrintInbox" (Read/Update/Insert content), connected to Print Jobs.
