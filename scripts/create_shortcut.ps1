# Create a Desktop shortcut that launches the platform.
# Keep this file ASCII-only.

param(
    [string]$Name = "Disaster Agent Platform",
    [string]$Target = ""
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
if (-not $Target) { throw "Target path is required." }
if (-not (Test-Path -LiteralPath $Target)) { throw "Target not found: $Target" }

$desktop = [Environment]::GetFolderPath('Desktop')
$linkPath = Join-Path $desktop ($Name + '.lnk')

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($linkPath)
$shortcut.TargetPath = $Target
$shortcut.WorkingDirectory = $root
$shortcut.Description = $Name
$shortcut.WindowStyle = 1
$shortcut.Save()

Write-Host ""
Write-Host "  Shortcut created:" -ForegroundColor Green
Write-Host "  $linkPath"
Write-Host ""

