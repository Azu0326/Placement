# Download Tailwind standalone CLI (v3) and a pinned Lucide UMD build.
# No Node/npm required.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Tools = $PSScriptRoot
$Vendor = Join-Path $Root 'static\vendor'

$TailwindVersion = 'v3.4.18'
$LucideVersion = '0.469.0'

New-Item -ItemType Directory -Force -Path $Tools, $Vendor | Out-Null

$twUrl = "https://github.com/tailwindlabs/tailwindcss/releases/download/$TailwindVersion/tailwindcss-windows-x64.exe"
$twOut = Join-Path $Tools 'tailwindcss.exe'
Write-Host "Fetching Tailwind $TailwindVersion ..."
Invoke-WebRequest -Uri $twUrl -OutFile $twOut -UseBasicParsing

$lucideUrl = "https://cdn.jsdelivr.net/npm/lucide@$LucideVersion/dist/umd/lucide.min.js"
$lucideOut = Join-Path $Vendor 'lucide.min.js'
Write-Host "Fetching Lucide $LucideVersion ..."
Invoke-WebRequest -Uri $lucideUrl -OutFile $lucideOut -UseBasicParsing

Write-Host "Done."
Write-Host "  $twOut"
Write-Host "  $lucideOut"
