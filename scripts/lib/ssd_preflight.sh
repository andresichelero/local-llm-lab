#!/usr/bin/env bash

require_wsl_ext4_path() {
  local path="$1" label="${2:-path}" filesystem
  [[ -e "$path" ]] || { echo "$label does not exist: $path" >&2; return 1; }
  filesystem="$(findmnt -n -o FSTYPE -T "$path" | tr -d '[:space:]')"
  [[ "$filesystem" == ext4 ]] || {
    echo "$label must be on the WSL ext4 SSD (found $filesystem): $path" >&2
    return 1
  }
}

require_llama_cpp_ssd_bundle() {
  local executable="$1" library_dir="$2" resolved library
  require_wsl_ext4_path "$executable" "llama-server" || return 1
  require_wsl_ext4_path "$library_dir" "llama.cpp library directory" || return 1
  resolved="$(LD_LIBRARY_PATH="$library_dir" ldd "$executable")" || {
    echo "Unable to resolve llama-server shared libraries: $executable" >&2
    return 1
  }
  if grep -E '/mnt/[de]/|not found' <<<"$resolved"; then
    echo "llama-server has unresolved or HDD-backed dependencies; refusing to benchmark." >&2
    return 1
  fi
  while IFS= read -r library; do
    [[ -z "$library" ]] && continue
    [[ "$library" == "$library_dir"/* ]] || {
      echo "llama.cpp library resolves outside the SSD bundle: $library" >&2
      return 1
    }
  done < <(awk '$1 ~ /^lib(llama|ggml|mtmd)/ && $2 == "=>" {print $3}' <<<"$resolved")
}
