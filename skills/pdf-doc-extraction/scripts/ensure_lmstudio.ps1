# Ensures LMStudio's local server is running and the requested model is loaded.
# Idempotent: safe to call repeatedly.
#
# Usage (PowerShell):
#   .\ensure_lmstudio.ps1                       # default: glm-ocr, ttl=600s, gpu=max
#   .\ensure_lmstudio.ps1 -Model gemma-4-e2b-it
#   .\ensure_lmstudio.ps1 -Model glm-ocr -TtlSeconds 1800 -Gpu 0.5
#
# Requires `lms` (LM Studio CLI) on PATH.

[CmdletBinding()]
param(
    [string]$Model = "glm-ocr",
    [int]$TtlSeconds = 600,
    [string]$Gpu = "max"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command lms -ErrorAction SilentlyContinue)) {
    throw "lms CLI not found on PATH. Install LM Studio and ensure its bin/ directory is on PATH."
}

# 1. Server up?
$status = lms server status --json | ConvertFrom-Json
if (-not $status.running) {
    Write-Host "Starting LMStudio server..."
    lms server start
    if ($LASTEXITCODE -ne 0) { throw "lms server start failed (exit $LASTEXITCODE)" }
    Start-Sleep -Milliseconds 500
    $status = lms server status --json | ConvertFrom-Json
    if (-not $status.running) { throw "Server reports not running after start" }
} else {
    Write-Host "LMStudio server already running on port $($status.port)."
}

# 2. Requested model loaded?
$loaded = lms ps --json | ConvertFrom-Json
$match = $loaded | Where-Object { $_.modelKey -eq $Model -or $_.identifier -eq $Model }
if (-not $match) {
    Write-Host "Loading model '$Model' (gpu=$Gpu, ttl=${TtlSeconds}s)..."
    lms load $Model --gpu $Gpu --ttl $TtlSeconds -y
    if ($LASTEXITCODE -ne 0) { throw "lms load failed for '$Model' (exit $LASTEXITCODE)" }
} else {
    Write-Host "Model '$Model' already loaded."
}

Write-Host "Ready: server up on :$($status.port), model '$Model' loaded."
