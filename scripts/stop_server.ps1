# Stop the platform server listening on the given port.
# Keep this file ASCII-only: Windows PowerShell 5.1 reads .ps1 files without a
# BOM using the ANSI code page, which corrupts non-ASCII characters.

param([int]$Port = 8000)

$ErrorActionPreference = 'SilentlyContinue'

$found = netstat -ano |
    Select-String 'LISTENING' |
    Select-String ":$Port\s" |
    ForEach-Object { ($_.ToString().Trim() -split '\s+')[-1] } |
    Sort-Object -Unique

if (-not $found) {
    Write-Host "  No running instance found on port $Port." -ForegroundColor Yellow
    exit 0
}

$stopped = @()
foreach ($processId in $found) {
    if ($processId -and $processId -ne '0') {
        Stop-Process -Id ([int]$processId) -Force
        $stopped += $processId
    }
}

if ($stopped.Count -gt 0) {
    Write-Host ("  Stopped platform server (PID: " + ($stopped -join ', ') + ")") -ForegroundColor Green
} else {
    Write-Host "  Could not stop the server. Please close the service window manually." -ForegroundColor Yellow
}
exit 0

