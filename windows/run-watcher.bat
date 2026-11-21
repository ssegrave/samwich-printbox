@echo off
REM PrintBox watcher - phase 1 (parse only). Close this window to stop it.
REM Run this on ONE machine only (the "processor"). Other PCs just sync via Google Drive.

REM Folder to watch. Change this line if your Google Drive path is different.
set "INBOX_DIR=G:\My Drive\PrintBox"

cd /d "%~dp0"
if not exist "%INBOX_DIR%" (
  echo Cannot find %INBOX_DIR%
  echo Is Google Drive for desktop running, and is the path above correct?
  pause
  exit /b 1
)
py -3 ..\watcher\watcher.py
pause
