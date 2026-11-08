# AuroraOS in QEMU für Windows starten (native, ohne WSL).
# Aufruf in PowerShell aus dem Projektordner:   .\run.ps1
# Mit GDB-Server:                               .\run.ps1 -Debug
param([switch]$Debug)

$qemuDir = "C:\Program Files\qemu"
$qemu    = Join-Path $qemuDir "qemu-system-x86_64.exe"
$ovmf    = Join-Path $qemuDir "share\edk2-x86_64-code.fd"   # UEFI-Firmware, liegt QEMU bei
$iso     = Join-Path $PSScriptRoot "build\aurora.iso"

if (-not (Test-Path $iso)) { Write-Error "ISO fehlt – zuerst in WSL 'make' ausführen."; exit 1 }

$qemuArgs = @(
    "-M", "q35", "-m", "512M",
    "-accel", "whpx,kernel-irqchip=off", "-accel", "tcg",   # Hyper-V-Beschleunigung, sonst Software
    "-drive", "if=pflash,format=raw,readonly=on,file=$ovmf",
    "-cdrom", $iso,
    "-serial", "stdio", "-no-reboot", "-no-shutdown"
)
if ($Debug) { $qemuArgs += @("-s", "-S") }

& $qemu @qemuArgs
