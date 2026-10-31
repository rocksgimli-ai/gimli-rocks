# Bakar agent watchdog.
#
# Keeps the voice-agent worker running around the clock on always-on hardware:
#   - starts the worker in production mode ("start", not "dev")
#   - restarts it automatically if it crashes
#   - optionally pulls the latest code from GitHub on every start (deploy by push)
#   - keeps the worker stopped during a daily maintenance window
#
# Install once (as Administrator) so it starts on every boot:
#   schtasks /Create /TN "Bakar agent watchdog" /SC ONSTART /RU SYSTEM /RL HIGHEST `
#     /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File S:\Bakar\backend\scripts\run-agent-watchdog.ps1 -UvPath C:\Users\<you>\.local\bin\uv.exe"
# Remove:
#   schtasks /Delete /TN "Bakar agent watchdog" /F
#
# Logs: backend\logs\watchdog-YYYYMMDD.log and worker-*.log

param(
    [string]$AgentDir = (Split-Path -Parent $PSScriptRoot),
    [string]$UvPath = "$env:USERPROFILE\.local\bin\uv.exe",
    [int]$MaintenanceStartHour = 4,   # local hour when the machine may rest (24h clock)
    [int]$MaintenanceMinutes = 60,    # 0 disables the window entirely
    [switch]$NoPull                   # skip git pull / uv sync on restart
)

$ErrorActionPreference = 'Continue'

if (-not (Test-Path $UvPath)) {
    $found = Get-Command uv -ErrorAction SilentlyContinue
    if ($found) { $UvPath = $found.Source } else { throw "uv not found at $UvPath" }
}
$git = (Get-Command git -ErrorAction SilentlyContinue).Source

$logDir = Join-Path $AgentDir 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-Log([string]$Message) {
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    $line | Tee-Object -FilePath (Join-Path $logDir ("watchdog-{0:yyyyMMdd}.log" -f (Get-Date))) -Append
}

function Test-InMaintenance {
    if ($MaintenanceMinutes -le 0) { return $false }
    $now = Get-Date
    $windowStart = (Get-Date -Hour $MaintenanceStartHour -Minute 0 -Second 0)
    $windowEnd = $windowStart.AddMinutes($MaintenanceMinutes)
    return $now -ge $windowStart -and $now -lt $windowEnd
}

# Never run two workers against the same LiveKit project.
$existing = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like '*agent.py*start*' }
if ($existing) {
    Write-Log "a worker is already running (pid $($existing.ProcessId)) - watchdog exiting"
    exit 0
}

Write-Log "watchdog started (pid $PID, dir $AgentDir, uv $UvPath)"

while ($true) {
    if (Test-InMaintenance) {
        Write-Log "maintenance window - worker stays stopped"
        while (Test-InMaintenance) { Start-Sleep -Seconds 60 }
        Write-Log "maintenance window over - resuming"
    }

    if ($git -and -not $NoPull) {
        # Anchor to the agent directory: when installed via schtasks the
        # process starts in C:\Windows\System32, where neither git nor uv
        # finds the repo or pyproject.toml.
        Push-Location $AgentDir
        try {
            $pull = & $git pull --ff-only 2>&1
            Write-Log ("git pull: " + (($pull | Out-String).Trim()))
            & $UvPath sync --locked 2>&1 | ForEach-Object { Write-Log "uv sync: $_" }
        } finally {
            Pop-Location
        }
    }

    $workerLog = Join-Path $logDir ("worker-{0:yyyyMMdd-HHmmss}.log" -f (Get-Date))
    Write-Log "starting worker (output: $workerLog)"
    $proc = Start-Process -FilePath $UvPath `
        -ArgumentList 'run', '--no-sync', 'python', 'src/agent.py', 'start' `
        -WorkingDirectory $AgentDir -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $workerLog `
        -RedirectStandardError (Join-Path $logDir 'worker-error.log')

    if (-not $proc) {
        Write-Log 'failed to start worker - retrying in 60s'
        Start-Sleep -Seconds 60
        continue
    }
    Write-Log "worker pid $($proc.Id)"

    while (-not $proc.HasExited) {
        Start-Sleep -Seconds 30
        if (Test-InMaintenance) {
            Write-Log 'maintenance window - stopping worker'
            & taskkill /T /F /PID $proc.Id 2>&1 | Out-Null
            break
        }
    }

    if ($proc.HasExited) { Write-Log "worker exited (code $($proc.ExitCode))" }
    Start-Sleep -Seconds 15
}
