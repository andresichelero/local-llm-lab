"""Loopback-only recorded model client and single-owner local engine lifecycle."""

from __future__ import annotations

import http.client
import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path

from benchmark.qwen_optimization import write_json

LAB = Path("/home/foxtrot/local-llm-benchmark")


class ModelProtocolError(RuntimeError):
    pass


class ModelBudgetExceeded(ModelProtocolError):
    pass


class ResourceUnavailable(RuntimeError):
    pass


class CapacityUnsupported(ResourceUnavailable):
    """The requested fixed configuration did not fit; not a model verdict."""



class EngineCompatibilityError(RuntimeError):
    pass


def llama_command(server, model, port, context, *, thinking=True, cache="q8_0"):
    return [
        str(server),
        "--model",
        str(model),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--alias",
        "local-qwen",
        "--ctx-size",
        str(context),
        "--parallel",
        "1",
        "--gpu-layers",
        "99",
        "--fit",
        "off",
        "--flash-attn",
        "on",
        "--cache-type-k",
        cache,
        "--cache-type-v",
        cache,
        "--threads",
        "6",
        "--batch-size",
        "512",
        "--ubatch-size",
        "128",
        "--jinja",
        "--reasoning",
        "on" if thinking else "off",
        "--reasoning-format",
        "deepseek",
        "--chat-template-kwargs",
        json.dumps({"enable_thinking": thinking}),
        "--cache-reuse",
        "0",
    ]


def gpu_free_mib():
    result = subprocess.check_output(
        [
            "/usr/lib/wsl/lib/nvidia-smi",
            "--query-gpu=memory.free",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        timeout=15,
    )
    return int(result.strip().splitlines()[0])


def ram_available_mib():
    lines = dict(
        line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
    )
    return int(lines["MemAvailable"].split()[0]) // 1024


class ApiClient:
    def __init__(
        self,
        port,
        output,
        *,
        generation=None,
        engine="llama.cpp",
        max_calls=120,
        wall_seconds=1800,
        max_tokens=4096,
        seed=101,
        model="local-qwen",
        context_tokens=16384,
    ):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("model endpoint must be a local integer port")
        self.port, self.output, self.engine = port, Path(output), engine
        self.output.mkdir(parents=True, exist_ok=True)
        self.generation = (
            generation
            if generation is not None
            else {
                "temperature": 0.6,
                "top_p": 0.95,
                "top_k": 20,
                "min_p": 0,
                "presence_penalty": 0,
                "repeat_penalty": 1,
            }
        )
        self.calls, self.max_calls = 0, max_calls
        self.started = time.monotonic()
        self.wall_seconds, self.max_tokens, self.seed = wall_seconds, max_tokens, seed
        self.metrics = []
        self.model = model
        self.metadata_calls = 0
        self.context_tokens = context_tokens
        self.counts = {"main": 0, "compaction": 0, "title": 0}

    def tokenize(self, text):
        remaining = self.wall_seconds - (time.monotonic() - self.started)
        if remaining <= 0:
            raise ModelBudgetExceeded("wall budget exhausted")
        self.metadata_calls += 1
        if self.metadata_calls > 20:
            raise ModelProtocolError("metadata budget exhausted")
        path = "/tokenize" if self.engine == "llama.cpp" else "/v1/token/encode"
        payload = (
            {"content": text, "add_special": False}
            if self.engine == "llama.cpp"
            else {"text": text, "add_bos_token": False}
        )
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.port, timeout=min(30, remaining)
        )
        try:
            connection.request(
                "POST",
                path,
                json.dumps(payload).encode(),
                {"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            data = json.loads(response.read(8 * 1024**2))
            write_json(
                self.output / f"metadata-{self.metadata_calls:02d}.json",
                {"request": payload, "response": data, "status": response.status},
            )
            if response.status != 200 or not isinstance(data.get("tokens"), list):
                raise ModelProtocolError("tokenizer endpoint did not return tokens")
            return data["tokens"]
        finally:
            connection.close()

    def chat(
        self, messages, tools=None, *, max_tokens=None, kind="main", allow_tools=True
    ):
        remaining = self.wall_seconds - (time.monotonic() - self.started)
        caps = {"main": self.max_calls, "compaction": 8, "title": 1}
        if kind not in caps:
            raise ValueError("unknown generation class")
        if self.counts[kind] >= caps[kind] or remaining <= 0:
            raise ModelBudgetExceeded("budget exhausted")
        self.calls += 1
        self.counts[kind] += 1
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "seed": self.seed,
            "max_tokens": max_tokens or self.max_tokens,
            **self.generation,
        }
        if self.engine == "llama.cpp":
            payload["cache_prompt"] = False
        elif "repeat_penalty" in payload:
            payload["repetition_penalty"] = payload.pop("repeat_penalty")
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto" if allow_tools else "none"
        request_path = self.output / f"request-{self.calls:04d}.json"
        write_json(request_path, payload)
        response_path = self.output / f"response-{self.calls:04d}.sse"
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.port, timeout=min(240, remaining)
        )
        started = time.monotonic()
        first_token = None
        message = {"role": "assistant", "content": ""}
        tool_calls = {}
        usage, finish, complete = None, None, False
        error = None
        try:
            connection.request(
                "POST",
                "/v1/chat/completions",
                json.dumps(payload).encode(),
                {"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            if response.status != 200:
                body = response.read(16384).decode(errors="replace")
                raise ModelProtocolError(f"HTTP {response.status}: {body}")
            with response_path.open("wb") as raw:
                total = 0
                while True:
                    if time.monotonic() - self.started > self.wall_seconds:
                        raise ModelBudgetExceeded("wall budget exhausted")
                    line = response.readline(1024 * 1024)
                    if not line:
                        break
                    total += len(line)
                    if total > 32 * 1024**2:
                        raise ModelProtocolError("response exceeded 32 MiB")
                    raw.write(line)
                    raw.flush()
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        complete = True
                        break
                    event = json.loads(data)
                    if event.get("error"):
                        raise ModelProtocolError(str(event["error"]))
                    if event.get("usage"):
                        usage = event["usage"]
                    for choice in event.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if first_token is None and (
                            delta.get("content")
                            or delta.get("reasoning_content")
                            or delta.get("tool_calls")
                        ):
                            first_token = time.monotonic() - started
                        for field in ("content", "reasoning_content"):
                            if delta.get(field):
                                message[field] = message.get(field, "") + delta[field]
                        for call in delta.get("tool_calls") or []:
                            index = call["index"]
                            current = tool_calls.setdefault(
                                index,
                                {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                },
                            )
                            if call.get("id"):
                                current["id"] += call["id"]
                            for key in ("name", "arguments"):
                                current["function"][key] += (
                                    call.get("function") or {}
                                ).get(key, "")
                        finish = choice.get("finish_reason") or finish
            if not complete:
                raise ModelProtocolError("incomplete SSE stream; no DONE marker")
            if tool_calls:
                message["tool_calls"] = [tool_calls[key] for key in sorted(tool_calls)]
            result = {
                "choices": [{"message": message, "finish_reason": finish}],
                "usage": usage,
            }
            write_json(self.output / f"response-{self.calls:04d}.json", result)
            return result
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            connection.close()
            elapsed = time.monotonic() - started
            metric = {
                "seconds": elapsed,
                "ttft_seconds": first_token,
                "usage": usage,
                "kind": kind,
                "stream_complete": complete,
                "error": error,
            }
            if (
                usage
                and usage.get("completion_tokens")
                and first_token is not None
                and elapsed > first_token
            ):
                metric["decode_tokens_per_second"] = usage["completion_tokens"] / (
                    elapsed - first_token
                )
            self.metrics.append(metric)
            write_json(self.output / "metrics.json", self.metrics)


class ModelServer:
    def __init__(
        self, artifact_path, engine, output, context, *, thinking=True, cache="q8_0",
        gpu_free_floor_mib=7000, gpu_reserve_mib=512,
    ):
        self.model, self.engine, self.output = Path(artifact_path), engine, Path(output)
        self.context, self.thinking, self.cache = context, thinking, cache
        if any(type(x) is not int or x < 0 for x in (gpu_free_floor_mib, gpu_reserve_mib)):
            raise ValueError("GPU limits must be non-negative integer MiB")
        self.gpu_free_floor_mib = gpu_free_floor_mib
        self.gpu_reserve_mib = gpu_reserve_mib
        self.process = None
        self.log = None
        self.port = None

    def __enter__(self):
        if gpu_free_mib() < self.gpu_free_floor_mib or ram_available_mib() < 1536:
            raise ResourceUnavailable(
                f"capacity gate: need GPU {self.gpu_free_floor_mib} MiB and host available RAM 1536 MiB"
            )
        self.output.mkdir(parents=True, exist_ok=True)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.output / "home"),
            "CUDA_VISIBLE_DEVICES": "0",
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "DO_NOT_TRACK": "1",
        }
        Path(env["HOME"]).mkdir(exist_ok=True)
        if self.engine == "llama.cpp":
            binary = (LAB / "tools/llama-bin/llama-server").resolve(strict=True)
            env["LD_LIBRARY_PATH"] = str(binary.parent)
            command = llama_command(
                binary,
                self.model,
                self.port,
                self.context,
                thinking=self.thinking,
                cache=self.cache,
            )
            cwd = self.output
        elif self.engine == "exllamav3":
            base = LAB / "envs/qwen-engines-20261025"
            command = [str(base / "venv/bin/python"), str(base / "tabbyAPI/main.py")]
            # JSON is a YAML subset. All paths and API behavior are explicit.
            write_json(
                self.output / "config.yml",
                {
                    "network": {
                        "host": "127.0.0.1",
                        "port": self.port,
                        "disable_auth": True,
                        "allowed_origins": [],
                        "disable_fetch_requests": True,
                        "web_ui": False,
                    },
                    "model": {
                        "model_dir": str(self.model.parent),
                        "model_name": self.model.name,
                        "backend": "exllamav3",
                        "max_seq_len": self.context,
                        "cache_size": self.context,
                        "cache_mode": "Q8",
                        "vision": False,
                        "max_batch_size": 1,
                        "autosplit_reserve": [self.gpu_reserve_mib],
                        "inline_model_loading": False,
                        "use_dummy_models": False,
                        "template_vars_force": {"enable_thinking": self.thinking},
                    },
                    "logging": {"log_chat_completion_requests": True},
                },
            )
            env["PATH"] = str(base / "venv/bin") + ":" + env["PATH"]
            cwd = self.output
        else:
            raise ResourceUnavailable(
                "unsupported engine; qualification required: " + self.engine
            )
        write_json(
            self.output / "launch.json",
            {
                "command": command,
                "engine": self.engine,
                "context": self.context,
                "thinking": self.thinking,
                "cache": self.cache,
            },
        )
        self.log = (self.output / "server.log").open("ab", buffering=0)
        self.process = subprocess.Popen(
            command,
            env=env,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        started = time.monotonic()
        try:
            write_json(
                self.output / "server-process.json",
                {
                    "pid": self.process.pid,
                    "starttime": Path(f"/proc/{self.process.pid}/stat")
                    .read_text()
                    .split()[21],
                },
            )
            while time.monotonic() - started < 180:
                if self.process.poll() is not None:
                    raw = (self.output / "server.log").read_text(errors="replace")[
                        -32000:
                    ]
                    if any(
                        text in raw.lower()
                        for text in (
                            "out of memory",
                            "cudamalloc failed",
                            "not enough memory",
                            "failed to allocate cuda",
                        )
                    ):
                        raise CapacityUnsupported(
                            "engine reports allocation failure; preserve server.log"
                        )
                    raise EngineCompatibilityError(
                        "server exited before readiness; inspect server.log for compatibility/infra cause"
                    )
                if ram_available_mib() < 1024:
                    raise ResourceUnavailable(
                        "host RAM reserve exhausted during model loading"
                    )
                connection = http.client.HTTPConnection(
                    "127.0.0.1", self.port, timeout=3
                )
                try:
                    connection.request("GET", "/v1/models")
                    response = connection.getresponse()
                    data = json.loads(response.read())
                    models = data.get("data") or []
                    if response.status == 200 and models:
                        if gpu_free_mib() < self.gpu_reserve_mib:
                            raise CapacityUnsupported(
                                f"model loaded but leaves less than {self.gpu_reserve_mib} MiB GPU reserve"
                            )
                        self.alias = models[0]["id"]
                        return self
                except (OSError, ValueError, http.client.HTTPException):
                    pass
                finally:
                    connection.close()
                time.sleep(1)
            raise ResourceUnavailable("server startup exceeded 180 seconds")
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        pre_cleanup_returncode = self.process.poll() if self.process is not None else None
        if self.process is not None and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=10)
        if self.log:
            self.log.close()
        if self.process is not None:
            write_json(self.output / "server-exit.json", {
                "pre_cleanup_returncode": pre_cleanup_returncode,
                "final_returncode": self.process.poll(),
            })
