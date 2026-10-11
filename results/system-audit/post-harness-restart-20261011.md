# Post-harness storage and WSL check — 2026-10-11

Collected after the user-authorized WSL restart and archival of the completed harness-test models.

## WSL state

- Ubuntu-24.04 launched successfully after shutdown; kernel: `6.18.40.1-microsoft-standard-WSL2`.
- Memory: 7.8 GiB total, 511 MiB used, 6.3 GiB free, 7.3 GiB available. Swap: 4.0 GiB total, 0 bytes used.
- Root filesystem: 88 GiB total, 39 GiB used, 45 GiB available (47%). The VHD is on the C: SSD and remains 90 GB; `.wslconfig` keeps `defaultVhdSize=70GB` for newly created disks.
- E: archive filesystem: 932 GiB total, 857 GiB used, 75 GiB available.
- No Immich, Docker, containerd, Ollama, llama-server, or TrueForge process was present in the post-restart process check.

## Model staging policy and cleanup

- C: WSL ext4 is the active benchmark location. E: keeps the verified archive copies.
- Qwen3.5-9B Q4_K_M GGUF was archived on E: with SHA-256 `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`; the temporary C-side copy was removed only after path and checksum verification.
- All four Qwen2.5-Coder-7B-Instruct archive shards on E: matched their pinned SHA-256 values before the temporary C-side staging directory was removed.
- The 45 GiB free figure is the observed post-cleanup state and will change as later experiments stage assets on C:.
