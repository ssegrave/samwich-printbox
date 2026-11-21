@echo off
REM PrintBox opener - makes the Notion "Open" links work on this PC. Close this window to stop it.
REM Run this on EVERY PC that should open jobs (the watcher runs on one machine only).

REM Folder where jobs are synced. Change this line if your Google Drive path is different.
set "INBOX_DIR=G:\My Drive\PrintBox"

cd /d "%~dp0"
if not exist "%INBOX_DIR%" (
  echo Cannot find %INBOX_DIR%
  echo Is Google Drive for desktop running, and is the path above correct?
  pause
  exit /b 1
)
py -3 ..\watcher\opener.py
pause
