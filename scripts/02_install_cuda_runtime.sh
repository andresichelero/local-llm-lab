#!/usr/bin/env bash
set -euo pipefail
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --help) echo "Usage: $0 [--dry-run]"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done
if command -v nvcc >/dev/null 2>&1; then nvcc --version; echo "CUDA compiler already present; no changes made."; exit 0; fi
if ! command -v nvidia-smi >/dev/null 2>&1; then echo "No WSL NVIDIA driver interface found; refusing CUDA toolkit install." >&2; exit 1; fi
FREE_KIB="$(df -Pk / | awk 'NR==2 {print $4}')"
if ((FREE_KIB < 8000000)); then echo "Need at least 8 GiB free in WSL root; found $((FREE_KIB / 1024 / 1024)) GiB." >&2; exit 1; fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/tools"
KEYRING="$ROOT/tools/cuda-keyring_1.1-1_all.deb"
KEYRING_INSTALLED=0
if dpkg-query -W -f='${db:Status-Status}' cuda-keyring 2>/dev/null | grep -qx installed; then KEYRING_INSTALLED=1; fi
if ((DRY_RUN && KEYRING_INSTALLED == 0)); then
  echo "Would download and inspect NVIDIA's official WSL cuda-keyring package, add its signed apt source, then simulate cuda-toolkit-13-0 + g++-12."
  exit 0
fi
if ((EUID != 0)); then echo "Run installation with: wsl.exe -d Ubuntu-24.04 -u root -- bash scripts/02_install_cuda_runtime.sh"; exit 1; fi
if ((KEYRING_INSTALLED == 0)); then
  curl --fail --location --proto '=https' --tlsv1.2 --retry 3 \
    --output "$KEYRING" https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb
  dpkg-deb --info "$KEYRING"
  sha256sum "$KEYRING" | tee "$ROOT/results/system-audit/cuda-keyring.sha256"
  dpkg --install "$KEYRING"
fi
if ((DRY_RUN)); then
  echo "Dry run uses the currently cached apt package index."
else
  apt-get update
fi
PLAN="$(apt-get -s --no-install-recommends install cuda-toolkit-13-0 g++-12 2>&1)"
printf '%s\n' "$PLAN"
if grep -Eiq 'nvidia-driver|nvidia-dkms|nvidia-kernel|nvidia-compute-[0-9]' <<<"$PLAN"; then
  echo "The package plan includes a Linux NVIDIA driver; refusing to continue in WSL." >&2
  exit 1
fi
if ((DRY_RUN)); then exit; fi
apt-get install -y --no-install-recommends cuda-toolkit-13-0 g++-12
nvcc --version
nvidia-smi
