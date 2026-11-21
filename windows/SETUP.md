# PrintBox on samdesk - Phase 1 (parse only)

Code lives in `C:\Users\<you>\repos\samwich-printbox\` (a local folder, not synced by
OneDrive or Google Drive); the launcher is `windows\run-watcher.bat`. The drop folder is the Google Drive folder
`G:\My Drive\PrintBox\` (set in `run-watcher.bat`; edit that line if your path differs).
On first run the watcher adds `processed\`, `failed\` and `printbox.log` inside it.

Run the watcher on **one machine only** (samdesk for now). Other PCs just see the same
files through Google Drive - running a second watcher would create duplicate jobs.

## Step 1 - Python

PowerShell:

    py --version

Needs 3.10 or newer. If missing:

    winget install -e --id Python.Python.3.13

then open a new PowerShell window and re-check.

**Checkpoint 1:** `py --version` prints 3.10+.

## Step 2 - Start the watcher

Double-click `windows\run-watcher.bat`. A console window stays open showing activity.

**Checkpoint 2:** it prints `Watching G:\My Drive\PrintBox ...` and `processed`
and `failed` folders appear inside it.

## Step 3 - Real-file test (leave the console open)

Slice, then **File > Export > Export plate sliced file** into `G:\My Drive\PrintBox\`:

| # | Slicer       | Printer        | Plates |
|---|--------------|----------------|--------|
| a | Bambu Studio | P1S            | 1      |
| b | Bambu Studio | H3C (Mordecai) | 1      |
| c | OrcaSlicer   | P1S            | 1      |
| d | Bambu Studio | either         | 2+ ("Export all sliced file") |

Each should log `PARSED ...` within ~10 s and move to `processed\` with a `.json`
and `.plateN.png` beside it. Also drop an un-sliced project `.3mf`: it should go to
`failed\` with an `.error.txt`.

**Checkpoint 3:** tell Claude it's done - Claude can read the `.json` files from
`processed\` directly (no need to paste them).

## Notes

- Close the console window to stop the watcher. Running it hidden at login comes later.
- Same `watcher.py` runs unchanged on Linux / a Raspberry Pi (set `INBOX_DIR`; the Pi
  will sync the Drive folder with rclone).
