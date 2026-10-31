$ErrorActionPreference = "Stop"

function Test-CommandExists {
  param([string]$CommandName)

  return $null -ne (Get-Command $CommandName -ErrorAction SilentlyContinue)
}

if (-not (Test-CommandExists "uv")) {
  throw "Missing required command: uv"
}

if (-not (Test-CommandExists "pnpm")) {
  throw "Missing required command: pnpm"
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"

# Start each service in its own PowerShell window so logs remain visible.
#
# The command strings intentionally contain no absolute paths. PowerShell 5.1
# joins -ArgumentList without quoting, so embedding "$repoRoot" here truncated
# the path at the first space ("S:\Voice Agent Project\..." became "S:\Voice").
# -WorkingDirectory passes the path as a real parameter instead.
if (Test-CommandExists "livekit-server") {
  Start-Process powershell `
    -WorkingDirectory $repoRoot `
    -ArgumentList "-NoExit", "-Command", "livekit-server --dev"
} else {
  Write-Warning "livekit-server was not found. Skipping local LiveKit startup and using your configured LIVEKIT_URL instead."
}

Start-Process powershell `
  -WorkingDirectory $backendDir `
  -ArgumentList "-NoExit", "-Command", "uv run python src/agent.py dev"

Start-Process powershell `
  -WorkingDirectory $frontendDir `
  -ArgumentList "-NoExit", "-Command", "pnpm dev"

Write-Host "Started backend and frontend in separate PowerShell windows."
