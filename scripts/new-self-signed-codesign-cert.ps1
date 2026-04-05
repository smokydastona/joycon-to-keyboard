[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', '', Justification='Uses PSCredential; password is stored as SecureString and provided to Export-PfxCertificate.')]
param(
  [string]$SubjectName = "SmokyDaStona",
  [string]$OutputDir = ".\codesign_dev",
  [Parameter(Mandatory=$true)][PSCredential]$PfxCredential,
  [int]$ValidYears = 3,
  [switch]$TrustForCurrentUser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$subject = "CN=$SubjectName"
$outDir = Resolve-Path -LiteralPath $OutputDir -ErrorAction SilentlyContinue
if (-not $outDir) {
  New-Item -ItemType Directory -Path $OutputDir | Out-Null
  $outDir = Resolve-Path -LiteralPath $OutputDir
}

$pfxPath = Join-Path $outDir "codesign_$($SubjectName)_dev.pfx"
$cerPath = Join-Path $outDir "codesign_$($SubjectName)_dev.cer"

Write-Host "Creating self-signed code signing cert: $subject"

# Create in CurrentUser\My so it can be exported without admin.
$certParams = @{
  Subject           = $subject
  Type              = 'CodeSigningCert'
  KeyAlgorithm      = 'RSA'
  KeyLength         = 2048
  KeyExportPolicy   = 'Exportable'
  HashAlgorithm     = 'SHA256'
  CertStoreLocation = 'Cert:\CurrentUser\My'
  NotAfter          = (Get-Date).AddYears($ValidYears)
}

$cert = New-SelfSignedCertificate @certParams

if (-not $cert) {
  throw "Failed to create certificate"
}

# Export public cert (.cer)
Export-Certificate -Cert $cert -FilePath $cerPath | Out-Null

# Export PFX
Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $PfxCredential.Password | Out-Null

Write-Host "Wrote: $cerPath"
Write-Host "Wrote: $pfxPath"
Write-Host "Thumbprint: $($cert.Thumbprint)"

if ($TrustForCurrentUser) {
  Write-Host "Installing cert into CurrentUser TrustedPublisher and TrustedPeople (so Windows trusts your signature locally)."
  Import-Certificate -FilePath $cerPath -CertStoreLocation "Cert:\CurrentUser\TrustedPublisher" | Out-Null
  Import-Certificate -FilePath $cerPath -CertStoreLocation "Cert:\CurrentUser\TrustedPeople" | Out-Null
  Write-Host "Trusted for current user."
}

Write-Host "Note: self-signed certs will still look 'Unknown publisher' on other machines unless they also trust the .cer."
