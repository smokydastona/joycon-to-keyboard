param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

Write-Host "Setting core.hooksPath to .githooks in: $repoRoot" -ForegroundColor Cyan
Push-Location $repoRoot
try {
    $current = ''
    try { $current = (git config --local --get core.hooksPath) } catch { $current = '' }

    if (-not $Force -and $current -and $current.Trim() -ne '.githooks') {
        throw "core.hooksPath is already set to '$current'. Re-run with -Force to overwrite."
    }

    git config --local core.hooksPath .githooks

    # Ensure hooks are executable for Git Bash environments.
    try {
        git update-index --chmod=+x .githooks/pre-commit 2>$null
        git update-index --chmod=+x .githooks/pre-push 2>$null
    } catch {
        # ignore
    }

    Write-Host "Done. Hooks will now run on commit/push." -ForegroundColor Green
} finally {
    Pop-Location
}
