# Build static/css/app.css from static/src/input.css via Tailwind standalone CLI.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Cli = Join-Path $PSScriptRoot 'tailwindcss.exe'

if (-not (Test-Path $Cli)) {
  Write-Host 'tailwindcss.exe missing - running fetch-tooling.ps1'
  & (Join-Path $PSScriptRoot 'fetch-tooling.ps1')
}

$InputCss = Join-Path $Root 'static\src\input.css'
$OutputCss = Join-Path $Root 'static\css\app.css'

Push-Location $Root
try {
  & $Cli -i $InputCss -o $OutputCss --minify
  if ($LASTEXITCODE -ne 0) {
    throw "Tailwind build failed (exit $LASTEXITCODE)"
  }
  Write-Host "Wrote $OutputCss"
}
finally {
  Pop-Location
}
