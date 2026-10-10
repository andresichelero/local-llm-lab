#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/results/system-audit"
mkdir -p "$OUT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$OUT/wsl-audit-$STAMP.txt"
{
  echo "timestamp_utc=$STAMP"
  echo "=== distro ==="; lsb_release -a 2>&1 || true
  echo "=== kernel ==="; uname -a
  echo "=== cpu ==="; lscpu
  echo "=== memory and swap ==="; free -h; cat /proc/swaps
  echo "=== filesystems ==="; df -hT
  echo "=== block devices ==="; lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS,MODEL
  echo "=== NVIDIA ==="; nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free,utilization.gpu,temperature.gpu,clocks.gr,clocks.mem,power.draw,power.limit --format=csv,noheader 2>&1 || true
  echo "=== tool versions ==="
  for tool in python3 pip3 node npm pnpm cmake gcc g++ clang git uv ninja make; do
    printf '%s: ' "$tool"
    if command -v "$tool" >/dev/null 2>&1; then
      command -v "$tool"
      case "$tool" in
        pip3|npm|pnpm) "$tool" --version 2>&1 | head -1 || true ;;
        nvcc) "$tool" --version 2>&1 | tail -1 || true ;;
        *) "$tool" --version 2>&1 | head -1 || true ;;
      esac
    else
      echo unavailable
    fi
  done
  printf 'nvcc: '
  if [[ -x /usr/local/cuda/bin/nvcc ]]; then /usr/local/cuda/bin/nvcc --version | tail -1; elif command -v nvcc >/dev/null 2>&1; then nvcc --version | tail -1; else echo unavailable; fi
  echo "=== thermal zones ==="
  found=0
  for file in /sys/class/thermal/thermal_zone*/temp; do
    if [[ -r "$file" ]]; then printf '%s=' "$file"; cat "$file"; found=1; fi
  done
  [[ "$found" == 1 ]] || echo unavailable
  echo "=== PATH ==="; printf '%s\n' "$PATH"
} | tee "$FILE"
echo "Saved $FILE"
