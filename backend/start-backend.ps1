# Safe backend start: kills any stale process on :8010, then starts fresh.
# Usage: powershell -ExecutionPolicy Bypass -File start-backend.ps1
$ErrorActionPreference = "SilentlyContinue"
$conn = Get-NetTCPConnection -LocalPort 8010 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
  Write-Host "Killing stale PID $($conn.OwningProcess) on :8010..."
  Stop-Process -Id $conn.OwningProcess -Force
  Start-Sleep -Seconds 2
}
$expect = (Select-String -Path "main.py" -Pattern 'CODE_VERSION = "(.*)"').Matches[0].Groups[1].Value
Write-Host "Starting backend (expect version $expect)..."
Start-Process -FilePath "python" -ArgumentList "-m", "uvicorn", "main:app", "--port", "8010" `
  -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
Start-Sleep -Seconds 8
$live = (Invoke-RestMethod -Uri http://localhost:8010/api/version -TimeoutSec 15).version
if ($live -eq $expect) { Write-Host "OK: running $live" }
else { Write-Host "MISMATCH: disk=$expect running=$live - stale server still alive, investigate." }
