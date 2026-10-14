"""Owned, external system resource sampling for controlled campaign phases."""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ResourceMonitor:
    """A sampler outside candidate namespaces; measurements are system-wide."""

    process: subprocess.Popen[bytes]
    samples_path: Path
    log_path: Path
    _stopped: dict[str, Any] | None = None

    @classmethod
    def start(cls, output_dir: Path, *, run_id: str, phase_id: str,
              agent_id: str, parent_agent_id: str | None = None,
              interval: float = 1.0) -> ResourceMonitor:
        if not sys.platform.startswith("linux"):
            raise RuntimeError("resource monitor requires Linux")
        if not 0.25 <= interval <= 60:
            raise ValueError("sampling interval must be between 0.25 and 60 seconds")
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=False)
        samples = output_dir / "resources.jsonl"
        log = output_dir / "sampler.log"
        samples.touch(exist_ok=False)
        script = Path(__file__).with_name("resource_sampler.py")
        command = [sys.executable, "-I", str(script), "--output", str(samples),
                   "--interval", str(interval), "--run-id", run_id,
                   "--phase-id", phase_id, "--agent-id", agent_id]
        if parent_agent_id is not None:
            command.extend(["--parent-agent-id", parent_agent_id])
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib/wsl/lib",
               "LANG": "C.UTF-8", "PYTHONUTF8": "1"}
        with log.open("xb") as output:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output,
                                       stderr=subprocess.STDOUT, env=env,
                                       close_fds=True, start_new_session=True)
        monitor = cls(process, samples, log)
        deadline = time.monotonic() + 8
        while process.poll() is None and time.monotonic() < deadline:
            if samples.stat().st_size:
                return monitor
            time.sleep(0.05)
        evidence = monitor.stop()
        raise RuntimeError(f"resource sampler failed before candidate launch: {evidence['reason']}")

    def stop(self) -> dict[str, Any]:
        """Stop only our sampler process group and preserve failures as evidence."""
        if self._stopped is not None:
            return dict(self._stopped)
        escalated = False
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                escalated = True
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(timeout=3)
        data = self.samples_path.read_bytes()
        records: list[dict[str, Any]] = []
        invalid = False
        for line in data.splitlines():
            try:
                item = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                invalid = True
                continue
            if not isinstance(item, dict) or item.get("scope") != "system_wide":
                invalid = True
                continue
            records.append(item)
        complete = bool(records) and not invalid and self.process.returncode == 0 and not escalated
        self._stopped = {
            "status": "measured" if complete else "unavailable",
            "scope": "system_wide", "cleanup_verified": self.process.poll() is not None,
            "returncode": self.process.returncode, "escalated": escalated,
            "sample_count": len(records), "invalid_records": invalid,
            "path": str(self.samples_path), "log_path": str(self.log_path),
            "sha256": hashlib.sha256(data).hexdigest(),
            "reason": None if complete else "sampler_failed_or_no_complete_samples",
            "per_process_attribution": "unavailable",
        }
        return dict(self._stopped)
