[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', '', Justification='Uses PSCredential and never accepts plaintext password parameters. The password is only passed to signtool as required by its CLI.')]
param(
  [Parameter(Mandatory=$true)][string]$File,
  [Parameter(Mandatory=$true)][string]$PfxPath,
  [Parameter(Mandatory=$true)][PSCredential]$PfxCredential,
  [string]$TimestampUrl = "http://timestamp.digicert.com"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $File)) {
  throw "File not found: $File"
}
if (-not (Test-Path -LiteralPath $PfxPath)) {
  throw "PFX not found: $PfxPath"
}

function Find-SignTool {
  $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }

  $kits = @(
    "C:\Program Files (x86)\Windows Kits\10\bin",
    "C:\Program Files\Windows Kits\10\bin"
  )

  foreach ($root in $kits) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    $found = Get-ChildItem -LiteralPath $root -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
      Sort-Object FullName -Descending |
      Select-Object -First 1
    if ($found) { return $found.FullName }
  }

  throw "signtool.exe not found. Install Windows SDK (SignTool) or run on a machine that has it."
}

$signtool = Find-SignTool
Write-Host "Using signtool: $signtool"

$password = $PfxCredential.GetNetworkCredential().Password
& $signtool sign /fd sha256 /a /f $PfxPath /p $password /tr $TimestampUrl /td sha256 $File
& $signtool verify /pa /v $File

Write-Host "Signed: $File"
