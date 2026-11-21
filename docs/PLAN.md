# Plan & decisions

## Decisions (Nov 2026)
- **Local-first:** run on samdesk (Windows 11) now; move the watcher to a Raspberry Pi later.
  The old Ubuntu server laptop was overheating and is out of the loop.
- **Storage:** Google Drive for desktop, folder `My Drive\PrintBox` (available offline).
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
      - [x] Step 1: integration connected, schema read (API `2025-09-03`, rows go under
            the database's data source).
      - [x] Step 2: `watcher/notion.py` creates the row after the file is filed, then sets
            Open from the Job ID. Adds **Filaments** (text, per slot: `1: PLA Orange
            (#F99963) 4.16 g`) and **Colors** (multi-select, nearest color name from the
            slicer hex) if missing. Notion failures never fail the job; the `.json` gets
            `notion.synced=false`. Checkpoint passed (PRINT-2).
      - [x] Step 3: every plate PNG -> Preview (File Upload API: create `file_uploads`,
            multipart `send` with field `file`, attach as `{"type":"file_upload"}` in the
            create-page call). Upload failures are logged and the row is created without
            them. Checkpoint passed (PRINT-3, 2-plate `hacha`).
      - [ ] Step 4: retry unsynced jobs.
      - [x] Step 5 (done before Step 4, basics first): `watcher/opener.py` serves
            `localhost:8765/open/PRINT-N` (127.0.0.1 only), finds the job's .json in
            processed/ by Job ID and launches the slicer with the file: H3C -> Bambu Studio,
            else the slicer that made it; `?slicer=bambu|orca` overrides. Exe paths default
            to Program Files, override with BAMBU_STUDIO_EXE / ORCASLICER_EXE.
            `windows/run-opener.bat` runs it on every PC. Checkpoint passed: PRINT-3 opened
            in Bambu Studio 02.09 (new window, straight to sliced preview).
            OrcaSlicer launch tested on samdesk: opened as expected.
- [ ] **Phase 3 - background + install:** run hidden at login (Task Scheduler), one-command
      installer for new PCs.
      - [x] `windows/install.bat` (-> `install.ps1`): tasks "PrintBox Opener" (every PC) and
            "PrintBox Watcher" (`-Watcher`, processor only) run `pythonw` at logon, no admin;
            `-Uninstall` removes them. Re-running replaces and restarts the tasks (waits for
            the old process to exit so the opener's port is free).
      - [x] Watcher: per-PC lock (localhost port 8764) so a second copy exits; waits for the
            Drive folder at login. Opener: log at `%LOCALAPPDATA%\PrintBox\opener.log`,
            exclusive port bind (Windows SO_REUSEADDR allowed a second opener).
      - [x] Checkpoint A (partly): installed on samdesk, both tasks running hidden,
            PRINT-7 created by the background watcher.
      - [ ] Checkpoint A: click PRINT-7's Print link with only the background opener running.
      - [ ] Checkpoint B: sign out/in (or reboot), both start on their own; export -> row ->
            Print link works.
      - Notion **Print** column: formula showing the Job ID as a bold green link to Open
        (Button properties can't open per-row URLs and can't be created via the API).
- [ ] **Phase 4 - Pi:** watcher on Pi with rclone-synced Drive folder; PCs run opener only.

## Notion
- Print Jobs database: https://app.notion.com/p/41eda0e940bf81bc85ebcff87fda6ecf
- Integration: internal "PrintBox" (Read/Update/Insert content), connected to Print Jobs.
