from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DailyRuntimeUpdateTests(unittest.TestCase):
    def _write_executable(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def test_complete_same_day_update_skips_network_and_install_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state" / "runtime-updates"
            state.mkdir(parents=True)
            marker = state / f"daily-{date.today().isoformat()}.json"
            marker.write_text(
                json.dumps({"date": date.today().isoformat(), "status": "complete"}),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["BENCH_STORAGE_ROOT"] = temporary

            completed = subprocess.run(
                ["bash", str(ROOT / "scripts" / "00_update_runtime.sh")],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("already completed for today", completed.stdout)

    def test_daily_runner_finishes_update_preflight_before_starting_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state" / "runtime-updates"
            state.mkdir(parents=True)
            marker = state / f"daily-{date.today().isoformat()}.json"
            marker.write_text(
                json.dumps({"date": date.today().isoformat(), "status": "complete"}),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["BENCH_STORAGE_ROOT"] = temporary

            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "daily-run.sh"),
                    "bash",
                    "-c",
                    "printf 'target-command-ran\\n'",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertLess(
                completed.stdout.index("already completed for today"),
                completed.stdout.index("target-command-ran"),
            )

    def test_dry_run_resolves_latest_packages_from_long_pip_version_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            bench = base / "bench"
            llama_source = bench / "tools" / "llama.cpp"
            (llama_source / ".git").mkdir(parents=True)
            current_server = bench / "tools" / "llama-bin" / "llama-server"
            current_server.parent.mkdir(parents=True)
            current_server.write_text("stub", encoding="utf-8")
            current_server.chmod(0o755)

            node_runtime = bench / "runtimes" / "node"
            self._write_executable(node_runtime / "bin" / "node", "#!/bin/sh\nexit 0\n")
            self._write_executable(
                node_runtime / "bin" / "npm",
                "#!/usr/bin/env bash\n"
                "case \"$*\" in\n"
                "  *opencode-ai*) printf '1.19.3\\n' ;;\n"
                "  *@earendil-works/pi-coding-agent*) printf '1.3.0\\n' ;;\n"
                "  *@truefoundry/trueforge*) printf '0.179.2\\n' ;;\n"
                "  *) exit 2 ;;\n"
                "esac\n",
            )
            self._write_executable(
                bench / "envs" / "mistral-vibe" / "bin" / "python",
                "#!/usr/bin/env bash\n"
                "printf 'mistral-vibe (2.26.1)\\n'\n"
                "for ((i=0; i<100000; i++)); do printf '2.26.0, '; done\n",
            )
            fake_bin = base / "bin"
            self._write_executable(
                fake_bin / "git",
                "#!/usr/bin/env bash\n"
                "if [[ \"$1\" == '-C' && \"$3\" == 'status' ]]; then printf ' M existing-source-change\\n'; exit 0; fi\n"
                "if [[ \"$1\" == 'ls-remote' ]]; then printf '757cad021b357f417065ddbc41a6e8f87c1f8136\\trefs/tags/v0.7.0\\n'; exit 0; fi\n"
                "exit 2\n",
            )
            env = os.environ.copy()
            env["BENCH_STORAGE_ROOT"] = str(bench)
            env["LLAMA_CPP_SOURCE"] = str(llama_source)
            env["NODE_RUNTIME"] = str(node_runtime)
            env["PATH"] = f"{fake_bin}:{env['PATH']}"

            completed = subprocess.run(
                ["bash", str(ROOT / "scripts" / "00_update_runtime.sh"), "--dry-run"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("llama.cpp target: v0.7.0", completed.stdout)
            self.assertIn("Mistral Vibe target: 2.26.1", completed.stdout)

    def test_update_stops_before_network_when_cuda_compiler_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            bench = base / "bench"
            llama_source = bench / "tools" / "llama.cpp"
            llama_source.parent.mkdir(parents=True)
            current_server = bench / "tools" / "llama-bin" / "llama-server"
            current_server.parent.mkdir(parents=True)
            current_server.write_text("stub", encoding="utf-8")
            current_server.chmod(0o755)
            node_runtime = bench / "runtimes" / "node"
            self._write_executable(node_runtime / "bin" / "node", "#!/bin/sh\nexit 0\n")
            self._write_executable(node_runtime / "bin" / "npm", "#!/bin/sh\nexit 0\n")
            vibe_python = bench / "envs" / "mistral-vibe" / "bin" / "python"
            self._write_executable(vibe_python, "#!/bin/sh\nprintf 'mistral-vibe (2.26.1)\\n'\n")
            fake_bin = base / "bin"
            git_called = base / "git-was-called"
            self._write_executable(
                fake_bin / "git",
                "#!/usr/bin/env bash\n"
                f"printf 'called\\n' > '{git_called}'\n"
                "exit 1\n",
            )
            env = os.environ.copy()
            env["BENCH_STORAGE_ROOT"] = str(bench)
            env["LLAMA_CPP_SOURCE"] = str(llama_source)
            env["NODE_RUNTIME"] = str(node_runtime)
            env["CUDA_HOME"] = str(base / "cuda-missing")
            env["PATH"] = f"{fake_bin}:{env['PATH']}"

            completed = subprocess.run(
                ["bash", str(ROOT / "scripts" / "00_update_runtime.sh")],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("nvcc", completed.stderr)
            self.assertFalse(git_called.exists())


if __name__ == "__main__":
    unittest.main()
