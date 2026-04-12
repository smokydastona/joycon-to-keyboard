# clear_usb_cache.ps1 — Run as Administrator while device is UNPLUGGED
# Removes stale Windows USB registry cache for VID_CAFE&PID_4030 (Bind Bandit)
# so Windows re-enumerates fresh and reads the correct device names.

param()

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: This script must be run as Administrator." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "=== Bind Bandit USB Cache Cleaner ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "UNPLUG the USB cable NOW if you haven't already, then press Enter." -ForegroundColor Yellow
Read-Host

$keys = @(
    "HKLM:\SYSTEM\CurrentControlSet\Enum\USB\VID_CAFE&PID_4030",
    "HKLM:\SYSTEM\CurrentControlSet\Enum\USB\VID_CAFE&PID_4030&MI_00",
    "HKLM:\SYSTEM\CurrentControlSet\Enum\USB\VID_CAFE&PID_4030&MI_02",
    "HKLM:\SYSTEM\CurrentControlSet\Enum\USB\VID_CAFE&PID_4030&MI_03",
    "HKLM:\SYSTEM\CurrentControlSet\Enum\USB\VID_CAFE&PID_4030&MI_04"
)

$deleted = 0
foreach ($k in $keys) {
    if (Test-Path $k) {
        try {
            Remove-Item $k -Recurse -Force
            Write-Host "  Deleted: $k" -ForegroundColor Green
            $deleted++
        } catch {
            Write-Host "  FAILED:  $k  ($_)" -ForegroundColor Red
        }
    } else {
        Write-Host "  Not found (already clean): $k" -ForegroundColor DarkGray
    }
}

Write-Host ""
if ($deleted -gt 0) {
    Write-Host "Done. Plug the device back in — Windows will enumerate fresh." -ForegroundColor Cyan
    Write-Host "Expected names after replug:" -ForegroundColor Cyan
    Write-Host "  Ports (COM & LPT)              -> Architect" -ForegroundColor White
    Write-Host "  Keyboards                      -> Composer" -ForegroundColor White
    Write-Host "  Mice and other pointing devices -> Forger" -ForegroundColor White
    Write-Host "  Human Interface Devices        -> Executor" -ForegroundColor White
} else {
    Write-Host "Nothing to delete. Keys were already absent." -ForegroundColor Yellow
}

Write-Host ""
Read-Host "Press Enter to exit"
