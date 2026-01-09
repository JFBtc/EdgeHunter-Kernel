# V1a J7 Soak Test Protocol
#
# Runs the engine for extended duration (default 4 hours) to validate stability.
#
# Usage:
#   .\soak_run.ps1                    # 4 hour soak with MOCK feed
#   .\soak_run.ps1 -Duration 14400    # 4 hours (14400 seconds)
#   .\soak_run.ps1 -Duration 3600     # 1 hour test
#   .\soak_run.ps1 -FeedType IBKR     # Use real IBKR feed (requires credentials)
#
# After completion:
#   - Check console for shutdown summary report
#   - Validate TriggerCards JSONL: python -m src.triggercard_validator logs/triggercards_*.jsonl
#   - Review metrics: uptime_s, reconnect_count, staleness_events_count, max_cycle_time_ms

param(
    [int]$Duration = 14400,  # Default: 4 hours (14400 seconds)
    [string]$FeedType = "MOCK"  # MOCK or IBKR
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "V1a J7 SOAK TEST PROTOCOL" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Duration: $Duration seconds ($([math]::Round($Duration / 3600, 2)) hours)" -ForegroundColor Yellow
Write-Host "Feed Type: $FeedType" -ForegroundColor Yellow
Write-Host ""

# Validate feed type
if ($FeedType -ne "MOCK" -and $FeedType -ne "IBKR") {
    Write-Host "ERROR: FeedType must be 'MOCK' or 'IBKR'" -ForegroundColor Red
    exit 1
}

# Check Python environment
Write-Host "Checking Python environment..." -ForegroundColor Cyan
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Python not found. Please install Python 3.10+." -ForegroundColor Red
    exit 1
}
Write-Host "Found: $pythonVersion" -ForegroundColor Green

# Check dependencies
Write-Host "Checking dependencies..." -ForegroundColor Cyan
$pipCheck = python -c "import src.engine, src.datahub, src.triggercard_logger" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Missing dependencies. Run: pip install -r requirements.txt" -ForegroundColor Red
    exit 1
}
Write-Host "Dependencies OK" -ForegroundColor Green

# Create logs directory
if (-not (Test-Path "logs")) {
    Write-Host "Creating logs directory..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Path "logs" | Out-Null
}

# Set environment variables
$env:MAX_RUNTIME_S = $Duration
$env:FEED_TYPE = $FeedType
$env:ENABLE_TRIGGERCARD_LOGGER = "true"
$env:TRIGGERCARD_LOG_DIR = "logs"
$env:TRIGGERCARD_CADENCE_HZ = "1.0"  # 1 Hz for soak test

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "STARTING SOAK RUN" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Start time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Yellow
Write-Host ""

# Run the soak test
$startTime = Get-Date

try {
    python -m src.main
    $exitCode = $LASTEXITCODE
} catch {
    Write-Host ""
    Write-Host "ERROR: Soak run crashed with exception:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

$endTime = Get-Date
$actualDuration = ($endTime - $startTime).TotalSeconds

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "SOAK RUN COMPLETED" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "End time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Yellow
Write-Host "Actual duration: $([math]::Round($actualDuration, 2)) seconds ($([math]::Round($actualDuration / 3600, 2)) hours)" -ForegroundColor Yellow
Write-Host "Exit code: $exitCode" -ForegroundColor $(if ($exitCode -eq 0) { "Green" } else { "Red" })
Write-Host ""

# Validate TriggerCards JSONL
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "VALIDATING TRIGGERCARDS JSONL" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$jsonlFiles = Get-ChildItem -Path "logs" -Filter "triggercards_*.jsonl" | Sort-Object LastWriteTime -Descending

if ($jsonlFiles.Count -eq 0) {
    Write-Host "WARNING: No TriggerCards JSONL files found in logs/" -ForegroundColor Yellow
} else {
    Write-Host "Found $($jsonlFiles.Count) JSONL file(s)" -ForegroundColor Green
    Write-Host ""

    # Validate most recent file
    $latestFile = $jsonlFiles[0]
    Write-Host "Validating: $($latestFile.Name)" -ForegroundColor Cyan
    python -m src.triggercard_validator "logs\$($latestFile.Name)"
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "SOAK TEST PROTOCOL COMPLETE" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($exitCode -eq 0) {
    Write-Host "SUCCESS: Soak test completed without errors." -ForegroundColor Green
} else {
    Write-Host "FAILURE: Soak test exited with error code $exitCode." -ForegroundColor Red
}

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Review the shutdown summary report above" -ForegroundColor White
Write-Host "  2. Check TriggerCards validation results" -ForegroundColor White
Write-Host "  3. Review JSONL files in logs/ directory" -ForegroundColor White
Write-Host "  4. Verify metrics: uptime_s, reconnect_count, staleness_events_count" -ForegroundColor White
Write-Host ""

exit $exitCode
