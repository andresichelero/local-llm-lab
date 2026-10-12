import hashlib
import json
import os
import re
import signal
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


RUN = Path("/home/foxtrot/local-llm-benchmark/results/raw/mtp-activation-20261012")
RUNTIME = Path("/home/foxtrot/local-llm-benchmark/tools/llama-bin")
MODEL = Path("/home/foxtrot/local-llm-benchmark/models/gguf/qwen3.5-4b/Qwen_Qwen3.5-4B-Q4_K_M.gguf")
SOURCE_TAR = Path("/home/foxtrot/local-llm-benchmark/ssd-checkouts/round2-mtp-a734283-20261012/source.tar")
SERVER = RUNTIME / "llama-server"
BASE_URL = "http://127.0.0.1:18762"
PROMPT = "Repeat the sequence 0 1 2 3 4 5 6 7 8 9, separated by spaces, over and over."
ACTIVE_PROC = None
ARGV = [
    str(SERVER), "--offline", "--model", str(MODEL), "--host", "127.0.0.1", "--port", "18762",
    "--ctx-size", "16384", "--n-predict", "256", "--gpu-layers", "99", "--flash-attn", "on",
    "--cache-type-k", "q4_0", "--cache-type-v", "q4_0", "--no-cache-prompt", "--parallel", "1",
    "--spec-type", "draft-mtp", "--spec-draft-n-max", "3", "--reasoning", "off", "--temp", "0",
    "--metrics", "--slots", "--log-timestamps", "--verbosity", "4",
]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def get(path, timeout=5):
    request = urllib.request.Request(BASE_URL + path, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read()


def post_completion(body, timeout=115):
    encoded = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + "/completion", data=encoded,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read()


def request_fields(openapi):
    path = openapi.get("paths", {}).get("/completion", {}).get("post", {})
    schema = path.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
    reference = schema.get("$ref")
    while reference:
        name = reference.rsplit("/", 1)[-1]
        schema = openapi.get("components", {}).get("schemas", {}).get(name, {})
        reference = schema.get("$ref")
    return sorted(schema.get("properties", {}).keys())


def gpu_snapshot():
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu", "--format=csv,noheader"],
        capture_output=True, text=True, timeout=5, check=False,
    )
    return {"return_code": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}


def stop_owned_group(signum, _frame):
    if ACTIVE_PROC is not None and ACTIVE_PROC.poll() is None:
        try:
            os.killpg(ACTIVE_PROC.pid, signal.SIGTERM)
            ACTIVE_PROC.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(ACTIVE_PROC.pid, signal.SIGKILL)
            ACTIVE_PROC.wait(timeout=5)
        except ProcessLookupError:
            ACTIVE_PROC.wait(timeout=5)
    raise SystemExit(124 if signum == signal.SIGTERM else 128 + signum)


def main():
    signal.signal(signal.SIGTERM, stop_owned_group)
    signal.signal(signal.SIGINT, stop_owned_group)
    RUN.mkdir(parents=True, exist_ok=True)
    (RUN / "prompt.txt").write_text(PROMPT, encoding="utf-8")
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = str(RUNTIME) + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    ldd = subprocess.run(["ldd", str(SERVER)], capture_output=True, text=True, env=env, timeout=10, check=False)
    (RUN / "runtime-ldd.txt").write_text(ldd.stdout + ldd.stderr, encoding="utf-8")
    if ldd.returncode != 0 or "not found" in ldd.stdout:
        raise RuntimeError("runtime dependency preflight failed; server was not launched")
    runtime_hashes = {}
    for item in sorted(RUNTIME.iterdir()):
        if item.is_file() and (item.name.startswith("lib") or item.name in {"llama-server", "llama-cli"}):
            runtime_hashes[item.name] = sha256(item)
    preflight = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository_commit": "a734283cdb7941017f0a6129742249461880a1ec",
        "ssd_source_snapshot": str(SOURCE_TAR.parent),
        "ssd_source_archive_sha256": sha256(SOURCE_TAR),
        "model_path": str(MODEL), "model_sha256": sha256(MODEL),
        "runtime_path": str(RUNTIME), "runtime_version": "0.6.0-dev build 1 commit d81235049",
        "runtime_sha256": runtime_hashes,
        "prompt": PROMPT, "prompt_sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
        "server_argv": ARGV,
        "runtime_ld_library_path": env["LD_LIBRARY_PATH"],
        "ldd_return_code": ldd.returncode,
        "gpu_before": gpu_snapshot(),
        "wsl_df_before": subprocess.run(["df", "-BG", "/"], capture_output=True, text=True, check=False).stdout.strip(),
        "wsl_free_before": subprocess.run(["free", "-m"], capture_output=True, text=True, check=False).stdout.strip(),
    }
    (RUN / "preflight.json").write_text(json.dumps(preflight, indent=2) + "\n", encoding="utf-8")

    start = time.monotonic()
    launch_time = datetime.now(timezone.utc).isoformat()
    response_status = None
    completion_error = None
    openapi_fields = []
    openapi_status = None
    health_status = None
    slots_status = None
    metrics_status = None
    completion_body = {
        "prompt": PROMPT,
        "n_predict": 256,
        "temperature": 0,
        "ignore_eos": True,
        "cache_prompt": False,
    }
    proc = None
    log_path = RUN / "server.log"
    with log_path.open("wb") as log:
        proc = subprocess.Popen(ARGV, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        global ACTIVE_PROC
        ACTIVE_PROC = proc
        try:
            for _ in range(45):
                if proc.poll() is not None:
                    raise RuntimeError(f"server exited during startup with return code {proc.returncode}")
                try:
                    health_status, health_body = get("/health", timeout=2)
                    (RUN / "health.json").write_bytes(health_body)
                    if health_status == 200:
                        break
                except Exception:
                    time.sleep(1)
            else:
                raise TimeoutError("health readiness exceeded 45 seconds")

            try:
                openapi_status, openapi_body = get("/openapi.json", timeout=8)
                (RUN / "openapi.json").write_bytes(openapi_body)
                openapi = json.loads(openapi_body)
                openapi_fields = request_fields(openapi)
            except Exception as exc:
                completion_error = f"OpenAPI retrieval/parse failed: {type(exc).__name__}: {exc}"
                raise RuntimeError(completion_error) from exc
            required = {"prompt", "n_predict", "temperature", "ignore_eos", "cache_prompt"}
            if not required.issubset(set(openapi_fields)):
                completion_error = f"/completion schema lacks required fields: {sorted(required - set(openapi_fields))}"
                raise RuntimeError(completion_error)
            (RUN / "completion-request.json").write_text(json.dumps(completion_body, indent=2) + "\n", encoding="utf-8")
            try:
                response_status, completion_response = post_completion(completion_body)
                (RUN / "completion-response.json").write_bytes(completion_response)
            except Exception as exc:
                completion_error = f"completion request failed: {type(exc).__name__}: {exc}"
                raise
            try:
                slots_status, slots_body = get("/slots", timeout=5)
                (RUN / "slots.json").write_bytes(slots_body)
            except Exception as exc:
                (RUN / "slots-error.txt").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
            try:
                metrics_status, metrics_body = get("/metrics", timeout=5)
                (RUN / "metrics.txt").write_bytes(metrics_body)
            except Exception as exc:
                (RUN / "metrics-error.txt").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        except Exception as exc:
            if completion_error is None:
                completion_error = f"{type(exc).__name__}: {exc}"
            (RUN / "run-error.txt").write_text(completion_error + "\n", encoding="utf-8")
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
                except ProcessLookupError:
                    proc.wait(timeout=5)
            return_code = proc.wait()
            ACTIVE_PROC = None
            group_gone = False
            try:
                os.killpg(proc.pid, 0)
            except ProcessLookupError:
                group_gone = True
            (RUN / "run.json").write_text(json.dumps({
                "started_at_utc": launch_time,
                "elapsed_seconds_including_cleanup": round(time.monotonic() - start, 3),
                "process_return_code": return_code,
                "process_group_released": group_gone,
                "health_status": health_status,
                "openapi_status": openapi_status,
                "openapi_completion_request_fields": openapi_fields,
                "completion_status": response_status,
                "completion_request": completion_body if response_status is not None else None,
                "completion_error": completion_error,
                "slots_status": slots_status,
                "metrics_status": metrics_status,
                "gpu_after_cleanup": gpu_snapshot(),
            }, indent=2) + "\n", encoding="utf-8")

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    activation_lines = [line for line in log_text.splitlines() if re.search(r"mtp|speculat|nextn|draft", line, re.I)]
    (RUN / "mtp-runtime-lines.txt").write_text("\n".join(activation_lines) + ("\n" if activation_lines else ""), encoding="utf-8")
    print(json.dumps(json.loads((RUN / "run.json").read_text(encoding="utf-8")), indent=2))


if __name__ == "__main__":
    main()
