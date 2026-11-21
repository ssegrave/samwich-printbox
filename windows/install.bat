@echo off
REM PrintBox installer. Double-click = opener only (every PC).
REM On the ONE processor PC run from a terminal:   windows\install.bat -Watcher
REM Remove everything:                              windows\install.bat -Uninstall
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
pause
