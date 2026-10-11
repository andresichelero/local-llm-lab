# Storage and WSL post-change audit — 2026-10-11

Collected after the user-authorized WSL restart and virtual disk resize.

## Host drives

Verified with Windows WMI and logical-disk-to-partition mapping:

- C: ANDROMEDA is on PHYSICALDRIVE3, Samsung SSD 970 EVO Plus 500GB. Free space after staging: 86 GB.
- E: ANTARES is on PHYSICALDRIVE0, WDC WD10JPVX-75JC3T0 1 TB hard disk. Free space after staging: 75 GB.
- D: SIRIUS and F: RIGEL are on 1 TB ST1000DM003 hard disks.

## WSL

- Ubuntu-24.04 was shut down cleanly after the QLoRA process exited with status 0, then restarted.
- User-authorized virtual disk size increased from 70 to 90 GB. Current ext4 filesystem: 88 GiB total, 50 GiB used, 34 GiB free.
- WSL sees 7.8 GiB RAM, 7.3 GiB available at idle, and 4 GiB swap with 0 bytes used.
- The WSL distribution base path is under C:\\Users\\Andre\\AppData\\Local\\wsl; its ext4 VHD therefore resides on the SSD.
- Docker, containerd, and snapd were inactive after restart. Immich remains stopped with the previously recorded restart policies.

## Staged QLoRA assets and validation

- The 15.24 GB Qwen2.5-Coder-7B-Instruct snapshot was copied from E: into `/home/foxtrot/local-llm-benchmark/models/Qwen2.5-Coder-7B-Instruct`. All four safetensors SHA-256 values match `download-manifest.json`; the E: original remains intact.
- The 7.75 GB training venv was copied from E: into `/home/foxtrot/local-llm-benchmark/envs/training`. Its `sys.prefix` resolves to the new SSD location.
- Imports passed for Torch 2.10.0+cu128, Transformers 5.19.0, PEFT 0.21.2, bitsandbytes 0.50.2, Accelerate, and TRL. Import wall time was 5.997 s. CUDA reported the RTX 3070, and a small CUDA tensor operation returned the expected sum.
- The next step is a same-configuration QLoRA repetition using the SSD paths. The helper `scripts/16_stage_benchmark_to_ssd.sh` can restage the assets without removing the E: archive.
