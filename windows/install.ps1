<#
PrintBox installer - runs the opener (and optionally the watcher) hidden at login.

  .\install.ps1              opener only (every PC that opens jobs)
  .\install.ps1 -Watcher     opener + watcher (the ONE processor PC, samdesk for now)
  .\install.ps1 -Uninstall   stop and remove both tasks

Creates Task Scheduler tasks "PrintBox Opener" / "PrintBox Watcher" for the current user,
started at login with pythonw (no window) and started right away. No admin needed.
Re-run after changing settings; it replaces the tasks. Logs:
  watcher: <INBOX_DIR>\printbox.log     opener: %LOCALAPPDATA%\PrintBox\opener.log
#>
param([switch]$Watcher, [switch]$Uninstall)
$ErrorActionPreference = 'Stop'

$Repo = Split-Path -Parent $PSScriptRoot
$Tasks = @{ 'PrintBox Opener' = 'opener.py'; 'PrintBox Watcher' = 'watcher.py' }

function Remove-PrintBoxTask($name) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        # Stopping is asynchronous: wait for the old process to exit and free its port,
        # or the new copy sees it still running and exits.
        for ($i = 0; $i -lt 20 -and (Get-ScheduledTask -TaskName $name).State -eq 'Running'; $i++) {
            Start-Sleep -Milliseconds 500
        }
        Start-Sleep -Seconds 1
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "Removed $name"
    }
}

if ($Uninstall) {
    $Tasks.Keys | ForEach-Object { Remove-PrintBoxTask $_ }
    return
}

# --- Python (windowless pythonw.exe next to python.exe) ---
$python = (& py -3 -c "import sys; print(sys.executable)").Trim()
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found next to $python" }

# --- .env (INBOX_DIR; plus NOTION_TOKEN for the watcher) ---
$envFile = Join-Path $Repo '.env'
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $Repo '.env.example') $envFile
    Write-Host "Created .env from .env.example - check INBOX_DIR in it."
}
$settings = @{}
Get-Content $envFile | Where-Object { $_ -match '^\s*([A-Z_]+)\s*=\s*(.*)$' } |
    ForEach-Object { $settings[$Matches[1]] = $Matches[2].Trim().Trim('"') }
$inbox = $settings['INBOX_DIR']
if (-not $inbox) { throw "Set INBOX_DIR in $envFile (e.g. G:\My Drive\PrintBox)" }
if (-not (Test-Path $inbox)) {
    Write-Warning "$inbox not found right now (Google Drive not running?). Tasks will wait for it."
}
if ($Watcher -and (-not $settings['NOTION_TOKEN'] -or $settings['NOTION_TOKEN'] -like 'ntn_xxx*')) {
    Write-Warning "NOTION_TOKEN isn't set in .env - the watcher will parse files but skip Notion."
}

# --- Tasks ---
$user = "$env:USERDOMAIN\$env:USERNAME"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

$wanted = @('PrintBox Opener')
if ($Watcher) { $wanted += 'PrintBox Watcher' }

foreach ($name in $wanted) {
    Remove-PrintBoxTask $name
    $script = Join-Path $Repo ('watcher\' + $Tasks[$name])
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$script`"" `
        -WorkingDirectory (Join-Path $Repo 'watcher')
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal `
        -Settings $taskSettings -Description "PrintBox: $($Tasks[$name]) (installed by windows\install.ps1)" | Out-Null
    Start-ScheduledTask -TaskName $name
    Write-Host "Installed and started $name"
}
if (-not $Watcher -and (Get-ScheduledTask -TaskName 'PrintBox Watcher' -ErrorAction SilentlyContinue)) {
    Write-Host "Note: 'PrintBox Watcher' is still installed from before (use -Uninstall to remove both)."
}

Start-Sleep -Seconds 3
foreach ($name in $wanted) {
    $info = Get-ScheduledTask -TaskName $name
    Write-Host ("{0}: {1}" -f $name, $info.State)
}
Write-Host "Opener log: $env:LOCALAPPDATA\PrintBox\opener.log"
if ($Watcher) { Write-Host "Watcher log: $inbox\printbox.log" }
