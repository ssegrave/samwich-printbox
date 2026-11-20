# samwich-printinbox

Print-job inbox for The Samwich Shop's Bambu printers.

Slice in Bambu Studio or OrcaSlicer -> export the plate (`.gcode.3mf`) into the shared
Google Drive folder `My Drive\PrintInbox` -> the watcher reads it and (Phase 2) logs it
to the Notion **Print Jobs** database -> an **Open** link loads the file in the right
slicer, where you confirm filament mapping and print.

No printer Developer Mode needed; printing stays in Bambu Studio / Bambu Connect.

## Layout

| Path | What |
|------|------|
| `watcher/watcher.py` | The watcher (Python 3.10+, standard library only). Same code on Windows, Linux, Pi. |
| `windows/` | `run-watcher.bat` launcher + `SETUP.md` for Windows PCs. |
| `docker/` | Dockerfile + compose for a Linux host / Raspberry Pi later. |
| `docs/PLAN.md` | Decisions, architecture and phase checklist. |
| `.env.example` | Per-machine settings template (copy to `.env`, never commit). |

## Quick start (Windows)

    mkdir $HOME\repos      # once; skip if it exists
    cd $HOME\repos
    git clone https://github.com/ssegrave/samwich-printinbox.git
    py --version            # 3.10+

Then follow `windows/SETUP.md`. Update later with `git pull` inside
`$HOME\repos\samwich-printinbox`.

Keep the repo out of OneDrive / Google Drive folders (sync tools and git don't mix).

Run the watcher on **one machine only**; other PCs just see the files through Google Drive.
