param(
  [Parameter(Mandatory=$true)][string]$PfxPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $PfxPath)) {
  throw "PFX not found: $PfxPath"
}

$bytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $PfxPath))
$b64 = [Convert]::ToBase64String($bytes)

# Print to stdout and also copy to clipboard for convenience.
$b64

try {
  Set-Clipboard -Value $b64
  Write-Host "(Copied base64 to clipboard)" -ForegroundColor DarkGray
} catch {
  # ignore
}
