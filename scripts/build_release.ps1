# Build the Beta distribution zip.
# Excludes runtime output, caches and the local secret file, then verifies
# that the archive contains no llm.local.json before reporting success.
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 files
# without a BOM using the ANSI code page, which corrupts non-ASCII characters.

param([string]$OutputDir = "")

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
if (-not $OutputDir) { $OutputDir = Split-Path -Parent $root }

$version = (Get-Content -LiteralPath (Join-Path $root 'VERSION') -Encoding utf8 |
    Select-Object -First 1).Trim()
$name = "disaster-agent-beta-$version"
$stageRoot = Join-Path $OutputDir '_build'
$stage = Join-Path $stageRoot $name
$zip = Join-Path $OutputDir "$name.zip"

$stageFull = [System.IO.Path]::GetFullPath($stage)
$stageRootFull = [System.IO.Path]::GetFullPath($stageRoot)
if (-not $stageFull.StartsWith($stageRootFull)) { throw "Unexpected staging path: $stageFull" }

if (Test-Path -LiteralPath $stageRoot) { Remove-Item -LiteralPath $stageRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$excludeDirs = @('output', '__pycache__', 'uploads', '_workdir', '.pytest_cache', '_build')
$excludeFiles = @('*.pyc', 'server.log', 'server.log.err', 'llm.local.json')
robocopy $root $stage /E /XD $excludeDirs /XF $excludeFiles /NFL /NDL /NJH /NJS /NP | Out-Null

if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -Path $stage -DestinationPath $zip -CompressionLevel Optimal

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($zip)
$leaked = @($archive.Entries | Where-Object { $_.FullName -like '*llm.local.json' })
$entryCount = $archive.Entries.Count
$archive.Dispose()
if ($leaked.Count -gt 0) {
    throw "SECURITY CHECK FAILED: archive contains llm.local.json - release aborted"
}

Remove-Item -LiteralPath $stageRoot -Recurse -Force

Write-Host ""
Write-Host "Build complete" -ForegroundColor Green
Write-Host "  version : $version"
Write-Host "  files   : $entryCount"
Write-Host "  archive : $zip"
Write-Host "  size    : $([math]::Round((Get-Item -LiteralPath $zip).Length / 1KB, 1)) KB"
Write-Host "  security: no secret file inside (passed)"
