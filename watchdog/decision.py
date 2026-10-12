"""Independent on-demand lifecycle for Laya; never switches the chat engine."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import secrets

from watchdog.config import MODELS_DIR, PACKAGE_DIR, DEFAULT_IDLE_TIMEOUT

INTERNAL_PORT = 8082
MODEL_ID = "laya-multilingual"
MODEL_DIR = Path(os.environ.get("LAYA_MODEL_DIR", MODELS_DIR / "Laya-Multilingual"))
PYTHON = Path(os.environ.get("LAYA_PYTHON", PACKAGE_DIR / ".venv" /
             ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")))
LOG_FILE = Path(tempfile.gettempdir()) / "llm-watchdog-laya.log"


class DecisionManager:
    def __init__(self):
        self.proc = None
        self.starting = False
        self.active_requests = 0
        self.last_active = time.monotonic()
        self.auto_sleep = True
        self.device = ""
        self.last_error = ""
        self._lock = None

    @property
    def lock(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def models(self):
        required = ("rl_agent_config.json", "model.safetensors", "encoder/config.json",
                    "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json")
        if not all((MODEL_DIR / name).is_file() for name in required):
            return []
        return [{"id": MODEL_ID, "name": "Laya multilingual", "path": str(MODEL_DIR),
                 "type": "laya", "idle_timeout": DEFAULT_IDLE_TIMEOUT}]

    def status(self):
        alive = self.proc is not None and self.proc.poll() is None
        models = self.models()
        remaining = max(0, int(DEFAULT_IDLE_TIMEOUT - (time.monotonic() - self.last_active))) if alive else 0
        return {"status": "starting" if self.starting else "running" if alive else "sleeping",
                "current_model": models[0]["name"] if models else "",
                "current_model_id": MODEL_ID if models else "", "models": models,
                "active_requests": self.active_requests, "device": self.device if alive else "",
                "idle_timeout": DEFAULT_IDLE_TIMEOUT, "idle_remaining": remaining,
                "auto_sleep_enabled": self.auto_sleep, "runtime_available": PYTHON.is_file(),
                "endpoint": "/v1/systemone", "last_error": self.last_error}

    async def _http(self, method, path, payload=None):
        reader, writer = await asyncio.open_connection("127.0.0.1", INTERNAL_PORT)
        try:
            body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else b""
            writer.write((f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                          f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode() + body)
            await writer.drain()
            header = await reader.readuntil(b"\r\n\r\n")
            length = next(int(line.split(b":", 1)[1]) for line in header.split(b"\r\n")
                          if line.lower().startswith(b"content-length:"))
            if not 0 <= length <= 1024 * 1024:
                raise RuntimeError("Invalid Laya response size")
            result = json.loads(await reader.readexactly(length))
            code = int(header.split(b" ", 2)[1])
            if code != 200:
                raise RuntimeError(result.get("error", {}).get("message", "Laya inference failed"))
            return result
        finally:
            writer.close()
            await writer.wait_closed()

    async def _start(self):
        if self.proc is not None and self.proc.poll() is None:
            return
        if not self.models():
            raise RuntimeError(f"Laya model files missing: {MODEL_DIR}")
        if not PYTHON.is_file():
            raise RuntimeError(f"Install watchdog/requirements-laya.txt in watchdog/.venv: {PYTHON}")
        self.starting = True
        self.last_error = ""
        try:
            startup_token = secrets.token_hex(16)
            env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
                       LAYA_STARTUP_TOKEN=startup_token, PYTHONUNBUFFERED="1")
            with LOG_FILE.open("w", encoding="utf-8") as log:
                self.proc = subprocess.Popen([str(PYTHON), "-m", "watchdog.laya_backend",
                                              "--model", str(MODEL_DIR), "--port", str(INTERNAL_PORT)],
                                             cwd=PACKAGE_DIR.parent, env=env, stdout=log, stderr=log,
                                             creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    raise RuntimeError("Laya failed to load; see " + str(LOG_FILE))
                try:
                    health = await asyncio.wait_for(self._http("GET", "/health"), 1)
                    # Windows venv launchers run Python in a child with a different PID.
                    # The inherited token identifies our backend without adopting another service.
                    if health.get("startup_token") != startup_token:
                        raise RuntimeError("Laya port 8082 is occupied by another process")
                    self.device = health.get("device", "")
                    self.last_active = time.monotonic()
                    return
                except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                    await asyncio.sleep(.25)
            raise RuntimeError("Laya startup timed out; see " + str(LOG_FILE))
        except Exception as error:
            self.last_error = str(error)
            self.stop()
            raise
        finally:
            self.starting = False

    async def wake(self):
        async with self.lock:
            await self._start()
            self.last_active = time.monotonic()

    async def evaluate(self, payload):
        self.active_requests += 1
        try:
            async with self.lock:
                await self._start()
                return await asyncio.wait_for(self._http("POST", "/v1/systemone", payload), 60)
        except Exception as error:
            self.last_error = str(error)
            raise
        finally:
            self.active_requests -= 1
            self.last_active = time.monotonic()

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)
        self.proc = None
        self.device = ""

    def check_idle(self):
        if self.auto_sleep and not self.starting and not self.active_requests and not self.lock.locked():
            if time.monotonic() - self.last_active >= DEFAULT_IDLE_TIMEOUT:
                self.stop()


decision = DecisionManager()


def validate_payload(payload):
    if not isinstance(payload, dict) or payload.get("state") is None:
        raise ValueError("Expected a JSON object with state and questions")
    if payload.get("model", MODEL_ID) not in (MODEL_ID, "jev-latest", "default", ""):
        raise ValueError("Unknown decision model")
    questions = payload.get("questions")
    if not isinstance(questions, dict) or not 1 <= len(questions) <= 32:
        raise ValueError("Expected 1–32 questions")
    for key, question in questions.items():
        if not isinstance(key, str) or len(key) > 128 or not isinstance(question, dict):
            raise ValueError("Invalid question")
        if question.get("type") not in ("noul", "choice", "score"):
            raise ValueError("Question type must be noul, choice or score")
        if not isinstance(question.get("instructions"), str) or len(question["instructions"]) > 4000:
            raise ValueError("Expected question instructions up to 4000 characters")
    return payload
