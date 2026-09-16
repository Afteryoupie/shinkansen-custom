"""
watchdog.manager
================
負責模型掃描、動態載入、llama-server / rapid-mlx 進程生命週期管理、
多模型平滑切換，以及定時閒置休眠檢查。
"""

import os
import sys
import time
import asyncio
import subprocess
from typing import List, Dict, Any, Tuple, Optional

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from watchdog.config import (
    MODELS_DIR,
    VENV_BIN,
    LLAMA_BIN,
    RAPID_BIN,
    OMLX_BIN,
    LLM_INTERNAL_PORT,
    DEFAULT_IDLE_TIMEOUT,
    is_translation_model,
)
from watchdog.state import state

def find_matching_mmproj(model_name: str) -> Optional[str]:
    """為 VL / 視覺多模態模型尋找對應的 mmproj 權重檔"""
    if not MODELS_DIR.exists():
        return None
    lower = model_name.lower()
    is_vl = any(k in lower for k in ["vl", "vision", "llava", "minicpm", "moondream", "pixtral", "ovis"])
    if not is_vl:
        return None
    for entry in MODELS_DIR.iterdir():
        if entry.is_file() and entry.suffix.lower() == ".gguf" and "mmproj" in entry.name.lower():
            if "qwen3" in lower and "vl" in lower and "qwen3" in entry.name.lower() and "vl" in entry.name.lower():
                return str(entry.resolve())
            if "qwen3vl" in lower and "qwen3vl" in entry.name.lower():
                return str(entry.resolve())
            return str(entry.resolve())
    return None

def scan_models() -> List[Dict[str, Any]]:
    """動態掃描 ~/LLM/Models 目錄並辨識 MLX、oQ/oMLX 與 GGUF 模型（Windows 自動過濾排除非 GGUF）"""
    discovered = []
    if not MODELS_DIR.exists():
        return discovered

    for entry in sorted(MODELS_DIR.iterdir()):
        if entry.name.startswith("."):
            continue

        # 排除 mmproj 視覺權重檔，不作為單獨 LLM 列出
        if "mmproj" in entry.name.lower():
            continue

        # Windows 端略過純 MLX / oMLX 目錄
        if sys.platform == "win32" and (entry.is_dir() and not list(entry.glob("*.gguf"))):
            continue

        if entry.is_dir():
            # 優先檢查目錄內是否有 .gguf 檔案
            ggufs = [g for g in entry.glob("*.gguf") if "mmproj" not in g.name.lower()]
            if ggufs:
                is_trans = is_translation_model(entry.name)
                discovered.append({
                    "id": entry.name,
                    "name": entry.name,
                    "path": str(ggufs[0].resolve()),
                    "type": "gguf",
                    "is_translation": is_trans,
                    "idle_timeout": DEFAULT_IDLE_TIMEOUT,
                })
            elif sys.platform != "win32" and ((entry / "oq_imatrix_report.json").exists() or "oq" in entry.name.lower()):
                is_trans = is_translation_model(entry.name)
                discovered.append({
                    "id": entry.name,
                    "name": entry.name,
                    "path": str(entry.resolve()),
                    "type": "omlx",
                    "is_translation": is_trans,
                    "idle_timeout": DEFAULT_IDLE_TIMEOUT,
                })
            elif sys.platform != "win32" and (entry / "config.json").exists():
                is_trans = is_translation_model(entry.name)
                discovered.append({
                    "id": entry.name,
                    "name": entry.name,
                    "path": str(entry.resolve()),
                    "type": "mlx",
                    "is_translation": is_trans,
                    "idle_timeout": DEFAULT_IDLE_TIMEOUT,
                })
        elif entry.is_file() and entry.suffix == ".gguf":
            is_trans = is_translation_model(entry.name)
            discovered.append({
                "id": entry.stem,
                "name": entry.stem,
                "path": str(entry.resolve()),
                "type": "gguf",
                "is_translation": is_trans,
                "idle_timeout": DEFAULT_IDLE_TIMEOUT,
            })

    # 排序：常用模型置頂（Qwen3VL / Hy-MT2 優先，再來是 Ling）
    def sort_key(m):
        nid = m["id"].lower()
        if "qwen3vl" in nid:
            return 0
        if "hy-mt2" in nid or "translate" in nid:
            return 1
        if "ling-3.0-tiny-mlx" in nid:
            return 2
        if "ling" in nid:
            return 3
        return 4

    discovered.sort(key=sort_key)
    return discovered

def init_models():
    """初始化載入可用模型，若有預設模型則設定為當前模型"""
    state.models = scan_models()
    if not state.models:
        raise FileNotFoundError(f"在 {MODELS_DIR} 找不到任何相容模型！")
    
    if not state.current_model:
        state.current_model = state.models[0]
        print(f"[系統] 預設模型: {state.current_model['name']} (類型: {state.current_model['type']})")

async def is_llm_ready() -> bool:
    """測試推論引擎內部連接埠是否已就緒（HTTP /health 200 OK）"""
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", LLM_INTERNAL_PORT)
        writer.write(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        await writer.drain()
        resp = await reader.read(512)
        writer.close()
        await writer.wait_closed()
        return b"200 OK" in resp or b'"ok"' in resp or b'"status":"ok"' in resp or b'"status": "ok"' in resp
    except Exception:
        return False

async def start_llm() -> bool:
    """按需啟動推論引擎進程 (Rapid-MLX 或 Llama.cpp)"""
    if state.lock is None:
        state.lock = asyncio.Lock()

    async with state.lock:
        if state.llm_proc and state.llm_proc.poll() is None:
            state.last_active_time = time.time()
            return True

        if state.is_starting:
            # 已經有其他協程正在拉起，等待完成
            for _ in range(200):
                await asyncio.sleep(0.1)
                if state.llm_proc and state.llm_proc.poll() is None:
                    state.last_active_time = time.time()
                    return True
                if not state.is_starting:
                    break
            return False

        if not state.current_model:
            init_models()

        m = state.current_model
        state.is_starting = True
        print(f"\n[⚡ 啟動] 正在拉起本地模型: {m['name']} ({m['type'].upper()})...", flush=True)

        try:
            if m["type"] == "gguf":
                ctx = "4096" if m["is_translation"] else "8192"
                cmd = [
                    str(LLAMA_BIN),
                    "--model", m["path"],
                    "--host", "127.0.0.1",
                    "--port", str(LLM_INTERNAL_PORT),
                    "--ctx-size", ctx,
                    "--n-gpu-layers", "99",
                    "--batch-size", "512",
                    "--ubatch-size", "512",
                    "--flash-attn", "on",
                    "--cache-type-k", "q8_0",
                    "--cache-type-v", "q8_0",
                ]
                mmproj_path = find_matching_mmproj(m["name"])
                if mmproj_path:
                    cmd.extend(["--mmproj", mmproj_path])
            elif m["type"] == "omlx":
                cmd = [
                    str(OMLX_BIN), "serve",
                    "--model-dir", str(MODELS_DIR),
                    "--host", "127.0.0.1",
                    "--port", str(LLM_INTERNAL_PORT),
                    "--log-level", "warning",
                ]
            else:
                max_tokens = "2048" if m["is_translation"] else "4096"
                if RAPID_BIN.is_file() and os.access(RAPID_BIN, os.X_OK):
                    cmd = [
                        str(RAPID_BIN), "serve",
                        m["path"],
                        "--host", "127.0.0.1",
                        "--port", str(LLM_INTERNAL_PORT),
                        "--max-tokens", max_tokens,
                        "--log-level", "WARNING",
                        "--watchdog-ppid", str(os.getpid()),
                    ]
                else:
                    cmd = [
                        str(VENV_BIN / "python3"), "-m", "mlx_lm.server",
                        "--model", m["path"],
                        "--host", "127.0.0.1",
                        "--port", str(LLM_INTERNAL_PORT),
                        "--max-tokens", max_tokens,
                    ]

            env = os.environ.copy()
            env["TRANSFORMERS_VERBOSITY"] = "error"
            env["PYTHONWARNINGS"] = "ignore::UserWarning"
            env["HF_HUB_OFFLINE"] = "1"

            popen_kwargs = {
                "args": cmd,
                "env": env,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                popen_kwargs["startupinfo"] = startupinfo

            state.llm_proc = subprocess.Popen(**popen_kwargs)

            # 等待就緒 (最多 25 秒)
            t0 = time.time()
            while time.time() - t0 < 25:
                if state.llm_proc.poll() is not None:
                    print(f"[✗ 錯誤] LLM 進程意外終止 (退出碼: {state.llm_proc.returncode})", flush=True)
                    state.llm_proc = None
                    return False
                if await is_llm_ready():
                    cost = time.time() - t0
                    print(f"[✓ 就緒] {m['name']} 已就緒！耗時 {cost:.2f}s (PID: {state.llm_proc.pid})", flush=True)
                    state.last_active_time = time.time()
                    return True
                await asyncio.sleep(0.1)

            print("[✗ 逾時] 等待 LLM 啟動逾時", flush=True)
            return False
        finally:
            state.is_starting = False

def stop_llm():
    """關閉 LLM 推論進程並 100% 釋放 GPU 顯存與記憶體"""
    if state.llm_proc and state.llm_proc.poll() is None:
        pid = state.llm_proc.pid
        print(f"\n[💤 休眠] 關閉 LLM (PID: {pid}) 釋放顯存與記憶體...", flush=True)
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                try:
                    state.llm_proc.wait(timeout=2)
                except Exception:
                    pass
            else:
                subprocess.run(["pkill", "-TERM", "-P", str(pid)], capture_output=True)
                state.llm_proc.terminate()
                try:
                    state.llm_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    state.llm_proc.kill()
        except Exception:
            pass
        state.llm_proc = None
        state.active_requests = 0
        print("[✓ 已休眠] 顯存與記憶體已 100% 釋放。\n", flush=True)

async def switch_model(target_id: str) -> Tuple[bool, str]:
    """一鍵切換模型：切換即啟動"""
    if state.lock is None:
        state.lock = asyncio.Lock()

    async with state.lock:
        state.models = scan_models()
        target = next((m for m in state.models if m["id"] == target_id or m["name"] == target_id), None)
        if not target:
            return False, f"找不到模型: {target_id}"

        if state.current_model and state.current_model["id"] == target["id"] and state.llm_proc and state.llm_proc.poll() is None:
            return True, "模型已在運行中"

        print(f"\n[🔄 切換模型] 切換至: {target['name']}", flush=True)
        stop_llm()
        state.current_model = target

    ok = await start_llm()
    if ok:
        return True, f"已成功切換並啟動 {target['name']}"
    else:
        return False, f"切換至 {target['name']} 但啟動失敗"

async def idle_checker():
    """定時檢查閒置狀態：全模型預設 3 分鐘自動休眠（若關閉自動休眠則保持常駐）"""
    while not state.should_exit:
        await asyncio.sleep(2)
        if not state.auto_sleep_enabled:
            continue
        if state.llm_proc and state.llm_proc.poll() is None and state.active_requests == 0:
            m = state.current_model
            timeout = m.get("idle_timeout", 0) if m else 0
            if timeout > 0:
                elapsed = time.time() - state.last_active_time
                if elapsed >= timeout:
                    stop_llm()
