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
PACKAGES=()
for package in build-essential cmake git python3-venv python3-dev curl; do
  dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null | grep -qx installed || PACKAGES+=("$package")
done
if (("${#PACKAGES[@]}" == 0)); then echo "Base packages are already installed."; exit 0; fi
printf 'Packages to install: %s\n' "${PACKAGES[*]}"
if ((DRY_RUN)); then
  apt-get -s install --no-install-recommends "${PACKAGES[@]}"
  exit
fi
if ((EUID == 0)); then apt-get install -y --no-install-recommends "${PACKAGES[@]}"; else sudo apt-get install -y --no-install-recommends "${PACKAGES[@]}"; fi
