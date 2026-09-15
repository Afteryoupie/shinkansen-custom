#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌐 本地 LLM 智慧守護代理 (Windows 專用版)
- 常駐監聽 8080（推論請求代理、API 控制與 Web 控制台）
- 待命狀態僅佔用 ~15MB RAM、0.0% CPU / 0% 顯存
- 自動動態掃描 Models 目錄下的所有 .gguf 模型
- 依模型分類智慧管理：
  * 翻譯模型 (如 Qwen3VL-8B GGUF)：閒置 3 分鐘自動休眠，釋放 100% 顯存
  * 編程/通用模型 (如 Ling-3.0 GGUF)：預設常駐不休眠，供長時間對話/編程
- 支援 REST API (/api/status, /api/switch, /api/sleep, /api/wake, /api/stop)
- 內建精美 Web 控制台 (http://127.0.0.1:8080/status) 隨時手動啟動/切換/休眠
- 外部工具標準端點 (http://127.0.0.1:8080/v1)，支援新幹線翻譯插件、OpenCode、Claude 等
- Windows 原生相容：使用 taskkill 管理進程樹，無 Unix 特有依賴
"""

import sys
import os
import time
import signal
import asyncio
import subprocess
import json
import urllib.parse
from pathlib import Path

# 基本目錄配置
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent.parent  # 指向 LLM 根目錄

# 尋找 Models 目錄（支援多種常見配置路徑）
CANDIDATE_MODELS_DIRS = [
    ROOT_DIR / "models",
    ROOT_DIR / "Models",
    Path(r"C:\LLM_Project\models"),
    SCRIPT_DIR / "Models",
    Path.cwd() / "Models",
    Path.home() / "LLM" / "Models",
]
MODELS_DIR = next((d for d in CANDIDATE_MODELS_DIRS if d.exists()), ROOT_DIR / "models")

# 尋找 llama-server.exe
CANDIDATE_LLAMA_BINS = [
    Path(r"C:\llama-win-vulkan-x64\llama-server.exe"),
    SCRIPT_DIR / "llama-server.exe",
    SCRIPT_DIR / "llama" / "llama-server.exe",
    ROOT_DIR / "llama" / "llama-server.exe",
    ROOT_DIR / "llama-server.exe",
]
LLAMA_BIN = next((b for b in CANDIDATE_LLAMA_BINS if b.is_file()), Path("llama-server.exe"))

PUBLIC_PORT = 8080
LLM_INTERNAL_PORT = 8081
DEFAULT_TRANSLATE_IDLE = 180  # 翻譯模型閒置 3 分鐘 (180 秒) 自動休眠

def is_translation_model(name: str) -> bool:
    lower = name.lower()
    return any(k in lower for k in ["qwen3vl", "mt", "translat", "hy-mt", "translate"])

def find_matching_mmproj(model_name: str) -> str | None:
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

def scan_models():
    """動態掃描 Models 目錄下的 GGUF 模型"""
    discovered = []
    if not MODELS_DIR.exists():
        return discovered

    for entry in sorted(MODELS_DIR.iterdir()):
        if entry.name.startswith("."):
            continue
        # 排除 mmproj 視覺權重檔，不作為單獨 LLM 列出
        if "mmproj" in entry.name.lower():
            continue
        if entry.is_dir():
            ggufs = [g for g in entry.glob("*.gguf") if "mmproj" not in g.name.lower()]
            if ggufs:
                is_trans = is_translation_model(entry.name)
                discovered.append({
                    "id": entry.name,
                    "name": entry.name,
                    "path": str(ggufs[0].resolve()),
                    "type": "gguf",
                    "is_translation": is_trans,
                    "idle_timeout": DEFAULT_TRANSLATE_IDLE if is_trans else 0,
                })
        elif entry.is_file() and entry.suffix.lower() == ".gguf":
            is_trans = is_translation_model(entry.name)
            discovered.append({
                "id": entry.stem,
                "name": entry.stem,
                "path": str(entry.resolve()),
                "type": "gguf",
                "is_translation": is_trans,
                "idle_timeout": DEFAULT_TRANSLATE_IDLE if is_trans else 0,
            })

    def sort_key(m):
        nid = m["id"].lower()
        if "qwen3vl-8b-uncensored-hauhaucs-aggressive-q4_k_m" in nid:
            return 0
        if "qwen3vl" in nid:
            return 1
        if "hy-mt2" in nid or "translate" in nid:
            return 2
        if "ling" in nid:
            return 3
        return 4

    discovered.sort(key=sort_key)
    return discovered

class State:
    llm_proc = None
    last_active_time = time.time()
    active_requests = 0
    is_starting = False
    current_model = None
    models = []
    lock = None
    stop_event = None
    should_exit = False

state = State()

def init_models():
    state.models = scan_models()
    if not state.models:
        print(f"[警告] 在 {MODELS_DIR} 尚未偵測到 .gguf 模型，請放入模型至該目錄。")
        return False
    if not state.current_model:
        target = next((m for m in state.models if "qwen3vl-8b-uncensored-hauhaucs-aggressive-q4_k_m" in m["id"].lower()), None)
        if target:
            state.current_model = target
        else:
            state.current_model = state.models[0]
        print(f"[系統] 預設模型: {state.current_model['name']} (GGUF)")
    return True

async def is_llm_ready():
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", LLM_INTERNAL_PORT)
        writer.write(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        await writer.drain()
        resp = await reader.read(512)
        writer.close()
        await writer.wait_closed()
        return b"200 OK" in resp or b'"ok"' in resp or b'"status":"ok"' in resp
    except Exception:
        return False

async def start_llm():
    async with state.lock:
        if state.llm_proc and state.llm_proc.poll() is None:
            return True

        if not state.current_model:
            ok = init_models()
            if not ok:
                return False

        m = state.current_model
        state.is_starting = True
        print(f"\n[⚡ 啟動] 正在拉起 Windows 本地模型: {m['name']}...", flush=True)

        try:
            # 檢查 llama-server.exe
            llama_exec = str(LLAMA_BIN)
            ctx = "4096" if m.get("is_translation", False) else "8192"

            cmd = [
                llama_exec,
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

            env = os.environ.copy()
            env["HF_HUB_OFFLINE"] = "1"

            # Windows 完全隱藏黑視窗，後台安靜運行
            startupinfo = None
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

            state.llm_proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
                startupinfo=startupinfo
            )

            # 等待就緒 (最多 30 秒)
            t0 = time.time()
            while time.time() - t0 < 30:
                if state.llm_proc.poll() is not None:
                    print(f"[✗ 錯誤] llama-server 意外退出 (代碼: {state.llm_proc.returncode})", flush=True)
                    print(f"  請確認是否已放置支援 CUDA/DirectML 的 llama-server.exe，或路徑是否正確：{llama_exec}")
                    state.llm_proc = None
                    return False
                if await is_llm_ready():
                    cost = time.time() - t0
                    print(f"[✓ 就緒] {m['name']} 已上線！耗時 {cost:.2f}s (PID: {state.llm_proc.pid})", flush=True)
                    state.last_active_time = time.time()
                    return True
                await asyncio.sleep(0.15)

            print("[✗ 逾時] 等待推論引擎啟動逾時", flush=True)
            return False
        except Exception as e:
            print(f"[✗ 異常] 啟動失敗: {e}", flush=True)
            return False
        finally:
            state.is_starting = False

def stop_llm():
    if state.llm_proc and state.llm_proc.poll() is None:
        pid = state.llm_proc.pid
        print(f"\n[💤 休眠] 關閉推論進程 (PID: {pid}) 釋放顯存...", flush=True)
        try:
            if sys.platform == "win32":
                # Windows 使用 taskkill 徹底終止整個進程樹 (無任何 cmd 快閃)
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                state.llm_proc.terminate()
                try:
                    state.llm_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    state.llm_proc.kill()
        except Exception as e:
            print(f"終止進程警告: {e}")
        state.llm_proc = None
        print("[✓ 已休眠] 顯存與記憶體已 100% 釋放。\n", flush=True)

async def switch_model(target_id: str):
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
    """定時檢查閒置狀態：翻譯模型 3 分鐘 (180 秒) 自動休眠釋放顯存"""
    while not state.should_exit:
        await asyncio.sleep(2)
        if state.llm_proc and state.llm_proc.poll() is None and state.active_requests == 0:
            m = state.current_model
            timeout = m.get("idle_timeout", 0) if m else 0
            if timeout > 0:
                elapsed = time.time() - state.last_active_time
                if elapsed >= timeout:
                    stop_llm()

# ── 代理伺服器核心 ──────────────────────────────────────────
async def handle_proxy_client(client_reader, client_writer):
    state.active_requests += 1
    state.last_active_time = time.time()
    try:
        initial_data = await client_reader.read(4096)
        if not initial_data:
            return

        header_str = initial_data.decode("utf-8", errors="ignore")
        first_line = header_str.split("\r\n")[0] if "\r\n" in header_str else ""
        parts = first_line.split(" ")
        if len(parts) < 2:
            return

        method = parts[0].upper()
        raw_path = parts[1]
        url_parts = urllib.parse.urlsplit(raw_path)
        path = url_parts.path
        query_params = urllib.parse.parse_qs(url_parts.query)

        # ── 處理 CORS OPTIONS 預檢 ──
        if method == "OPTIONS":
            cors_resp = (
                "HTTP/1.1 204 No Content\r\n"
                "Access-Control-Allow-Origin: *\r\n"
                "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
                "Access-Control-Allow-Headers: Content-Type, Authorization\r\n"
                "Access-Control-Max-Age: 86400\r\n"
                "Connection: close\r\n\r\n"
            ).encode("utf-8")
            client_writer.write(cors_resp)
            await client_writer.drain()
            return

        # ── REST API 端點 ────────────────────────────────────

        # 1. GET /api/status：回傳當前狀態與模型列表
        if path == "/api/status" and method == "GET":
            state.models = scan_models()
            llm_alive = state.llm_proc and state.llm_proc.poll() is None

            if state.is_starting:
                status_str = "starting"
            elif llm_alive:
                status_str = "running"
            else:
                status_str = "sleeping"

            m = state.current_model
            timeout = m.get("idle_timeout", 0) if m else 0
            if llm_alive and timeout > 0:
                rem = max(0, int(timeout - (time.time() - state.last_active_time)))
            else:
                rem = 0

            payload = {
                "status": status_str,
                "current_model": m["name"] if m else "",
                "current_model_id": m["id"] if m else "",
                "is_translation": m.get("is_translation", False) if m else False,
                "idle_timeout": timeout,
                "idle_remaining": rem,
                "models": state.models,
            }
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            resp = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: application/json; charset=utf-8\r\n"
                f"Access-Control-Allow-Origin: *\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("utf-8") + body
            client_writer.write(resp)
            await client_writer.drain()
            return

        # 2. POST /api/switch：切換模型
        if path == "/api/switch" and method in ("POST", "GET"):
            target_model = None
            if "model" in query_params:
                target_model = query_params["model"][0]
            else:
                body_str = header_str.split("\r\n\r\n", 1)[-1] if "\r\n\r\n" in header_str else ""
                if body_str:
                    try:
                        b_data = json.loads(body_str)
                        target_model = b_data.get("model")
                    except Exception:
                        pass

            if not target_model:
                body = json.dumps({"error": "缺少 model 參數"}).encode("utf-8")
                resp = f"HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8") + body
            else:
                ok, msg = await switch_model(target_model)
                body = json.dumps({"status": "ok" if ok else "error", "message": msg, "current_model": state.current_model["name"] if state.current_model else ""}).encode("utf-8")
                resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8") + body
            client_writer.write(resp)
            await client_writer.drain()
            return

        # 3. POST /api/sleep：立即休眠釋放顯存
        if path == "/api/sleep" and method in ("POST", "GET"):
            stop_llm()
            body = json.dumps({"status": "ok", "state": "sleeping"}).encode("utf-8")
            resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8") + body
            client_writer.write(resp)
            await client_writer.drain()
            return

        # 4. POST /api/wake 或 /api/start：手動喚醒
        if path in ("/api/wake", "/api/start") and method in ("POST", "GET"):
            ok = await start_llm()
            body = json.dumps({"status": "ok" if ok else "error", "state": "running" if ok else "failed"}).encode("utf-8")
            resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8") + body
            client_writer.write(resp)
            await client_writer.drain()
            return

        # 5. POST /api/stop 或 GET /stop：完全停止
        if path in ("/api/stop", "/stop", "/shutdown"):
            stop_llm()
            state.should_exit = True
            body = b'{"status":"stopped"}' if path.startswith("/api") else "<h1>🛑 Windows LLM 守護代理已關閉</h1>".encode("utf-8")
            ct = "application/json" if path.startswith("/api") else "text/html; charset=utf-8"
            resp = f"HTTP/1.1 200 OK\r\nContent-Type: {ct}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8") + body
            client_writer.write(resp)
            await client_writer.drain()
            if state.stop_event:
                asyncio.get_event_loop().call_later(0.3, state.stop_event.set)
            return

        # 6. GET /v1/models：標準 OpenAI 相容模型清單
        if path == "/v1/models" and method == "GET":
            state.models = scan_models()
            model_items = []
            for m in state.models:
                model_items.append({"id": m["id"], "object": "model", "created": 1700000000, "owned_by": "local-llm"})
                model_items.append({"id": m["path"], "object": "model", "created": 1700000000, "owned_by": "local-llm"})
            model_items.append({"id": "default", "object": "model", "created": 1700000000, "owned_by": "local-llm"})
            model_items.append({"id": "Qwen3VL-8B", "object": "model", "created": 1700000000, "owned_by": "local-llm"})
            model_items.append({"id": "Qwen3VL-8B-Uncensored-HauhauCS-Aggressive-Q4_K_M", "object": "model", "created": 1700000000, "owned_by": "local-llm"})

            body = json.dumps({"object": "list", "data": model_items}, ensure_ascii=False).encode("utf-8")
            resp = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: application/json; charset=utf-8\r\n"
                f"Access-Control-Allow-Origin: *\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("utf-8") + body
            client_writer.write(resp)
            await client_writer.drain()
            return

        # ── 7. 狀態儀表板 /status 或 / ──
        if (path == "/" or path == "/status") and method == "GET":
            state.models = scan_models()
            llm_alive = state.llm_proc and state.llm_proc.poll() is None
            m = state.current_model
            timeout = m.get("idle_timeout", 0) if m else 0

            if llm_alive:
                if timeout > 0:
                    rem = max(0, int(timeout - (time.time() - state.last_active_time)))
                    status_badge = f'<span class="badge badge-ok"><span class="status-dot pulse"></span> 運行中</span> <span class="badge badge-idle">閒置倒數: <b id="countdown-val">{rem}</b> 秒</span>'
                else:
                    status_badge = '<span class="badge badge-ok"><span class="status-dot pulse"></span> 運行中</span> <span class="badge badge-idle">常駐模式 (不休眠)</span>'
            else:
                status_badge = '<span class="badge badge-standby"><span class="status-dot"></span> 休眠待命中 (0% 顯存佔用)</span>'

            model_buttons_html = ""
            for item in state.models:
                is_cur = m and item["id"] == m["id"]
                is_trans = item.get("is_translation", False)
                strat_tag = "🌐 翻譯專用 (3分無請求自動釋放)" if is_trans else "⚡ 通用/編程 (常駐待命)"
                if is_cur:
                    model_buttons_html += f"""
                    <div class="model-card active">
                      <div class="model-meta">
                        <div class="model-name">📦 {item['name']}</div>
                        <div class="model-tags">
                          <span class="tag tag-coral">● 當前載入中</span>
                          <span class="tag tag-dim">{strat_tag}</span>
                        </div>
                      </div>
                      <span class="model-badge-active">使用中</span>
                    </div>"""
                else:
                    switch_url = f"/api/switch?model={urllib.parse.quote(item['id'])}"
                    model_buttons_html += f"""
                    <a href="{switch_url}" class="model-card inactive">
                      <div class="model-meta">
                        <div class="model-name">📦 {item['name']}</div>
                        <div class="model-tags">
                          <span class="tag tag-dim">{strat_tag}</span>
                        </div>
                      </div>
                      <span class="model-action-btn">切換載入 ➔</span>
                    </a>"""

            if not model_buttons_html:
                model_buttons_html = f'<div style="color:#9cb1c4;font-size:13px;padding:12px;background:#243443;border-radius:8px;border:1px dashed #475F77;">尚未在 <code>{MODELS_DIR}</code> 找到 .gguf 模型，請放入模型後重新整理。</div>'

            cur_model_name = m['name'] if m else '無 (待命中)'
            cur_model_type = ("🌐 翻譯模型" if (m and m.get("is_translation")) else ("⚡ 通用模型" if m else "待命"))
            strat_desc = '翻譯模型 3 分鐘無請求自動釋放顯存' if timeout > 0 else '常駐模式 (不自動休眠)'

            html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LLM 智慧守護代理控制台</title>
<style>
  :root {{
    --bg-root: #1c2833;
    --bg-surface: #273746;
    --bg-card: #354B5E;
    --bg-input: #243443;
    --border: #475F77;
    --border-focus: #D74B4B;
    --accent: #D74B4B;
    --accent-hover: #c43f3f;
    --accent-glow: rgba(215, 75, 75, 0.28);
    --btn-secondary: #475F77;
    --btn-secondary-hover: #56718d;
    --text-primary: #DCDDD8;
    --text-secondary: #9cb1c4;
    --text-dim: #6b8296;
    --badge-ok-bg: #1d3a33;
    --badge-ok-fg: #4ade80;
    --badge-ok-border: #2a5a4a;
    --badge-standby-bg: #243443;
    --badge-standby-fg: #9cb1c4;
    --badge-standby-border: #354b5e;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, "Microsoft JhengHei", Roboto, sans-serif;
    background-color: var(--bg-root);
    color: var(--text-primary);
    min-height: 100vh;
    padding: 32px 18px;
    display: flex;
    justify-content: center;
    align-items: flex-start;
  }}
  .dashboard {{
    width: 760px;
    max-width: 100%;
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-top: 3px solid var(--accent);
    border-radius: 16px;
    padding: 28px;
    box-shadow: 0 20px 45px rgba(0, 0, 0, 0.45);
  }}
  /* Header */
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 20px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 22px;
  }}
  .header-left h1 {{
    font-size: 20px;
    font-weight: 700;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .header-left .sub {{
    font-size: 13px;
    color: var(--text-secondary);
    margin-top: 4px;
  }}
  .pill-port {{
    background: var(--bg-input);
    border: 1px solid var(--border);
    color: var(--text-primary);
    padding: 6px 12px;
    border-radius: 20px;
    font-size: 12px;
    font-family: Consolas, monospace;
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .pill-dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 8px var(--accent);
  }}

  /* Bento Grid */
  .bento-grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 14px;
    margin-bottom: 22px;
  }}
  @media (max-width: 640px) {{
    .bento-grid {{ grid-template-columns: 1fr; }}
  }}
  .bento-card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 18px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }}
  .bento-label {{
    font-size: 12px;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
  }}
  .bento-value {{
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    word-break: break-all;
  }}
  .bento-value code {{
    font-family: Consolas, monospace;
    background: var(--bg-input);
    padding: 3px 6px;
    border-radius: 4px;
    border: 1px solid rgba(255,255,255,0.06);
    font-size: 13px;
    color: #ffffff;
  }}

  /* Badges */
  .badge {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: bold;
  }}
  .badge-ok {{
    background: var(--badge-ok-bg);
    color: var(--badge-ok-fg);
    border: 1px solid var(--badge-ok-border);
  }}
  .badge-idle {{
    background: var(--bg-input);
    color: var(--text-secondary);
    border: 1px solid var(--border);
    font-size: 12px;
    padding: 4px 8px;
    margin-left: 6px;
  }}
  .badge-idle b {{ color: var(--accent); }}
  .badge-standby {{
    background: var(--badge-standby-bg);
    color: var(--badge-standby-fg);
    border: 1px solid var(--badge-standby-border);
  }}
  .status-dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: currentColor;
  }}
  .status-dot.pulse {{
    animation: pulse 1.8s infinite;
  }}
  @keyframes pulse {{
    0% {{ box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.6); }}
    70% {{ box-shadow: 0 0 0 6px rgba(74, 222, 128, 0); }}
    100% {{ box-shadow: 0 0 0 0 rgba(74, 222, 128, 0); }}
  }}

  /* Action Buttons Toolbar */
  .actions-toolbar {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 24px;
  }}
  .btn {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 10px 18px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
    text-decoration: none;
    cursor: pointer;
    border: none;
    transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  }}
  .btn:hover {{
    transform: translateY(-1px);
  }}
  .btn-primary {{
    background: var(--accent);
    color: #ffffff;
    box-shadow: 0 4px 12px var(--accent-glow);
  }}
  .btn-primary:hover {{
    background: var(--accent-hover);
  }}
  .btn-secondary {{
    background: var(--btn-secondary);
    color: var(--text-primary);
  }}
  .btn-secondary:hover {{
    background: var(--btn-secondary-hover);
  }}
  .btn-danger {{
    background: #3d1a1e;
    color: var(--accent);
    border: 1px solid rgba(215, 75, 75, 0.4);
    margin-left: auto;
  }}
  .btn-danger:hover {{
    background: var(--accent-hover);
    color: #ffffff;
  }}

  /* Copy mini button */
  .btn-copy {{
    background: var(--btn-secondary);
    border: none;
    color: var(--text-primary);
    padding: 3px 8px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 11px;
    margin-left: 6px;
    vertical-align: middle;
  }}
  .btn-copy:hover {{
    background: var(--btn-secondary-hover);
  }}

  /* Models Section */
  .models-section {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px;
  }}
  .models-header {{
    font-size: 14px;
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 14px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .models-list {{
    display: flex;
    flex-direction: column;
    gap: 10px;
  }}
  .model-card {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    border-radius: 8px;
    text-decoration: none;
    transition: all 0.2s ease;
  }}
  .model-card.active {{
    background: rgba(215, 75, 75, 0.1);
    border: 2px solid var(--accent);
  }}
  .model-card.inactive {{
    background: var(--bg-input);
    border: 1px solid var(--border);
    cursor: pointer;
  }}
  .model-card.inactive:hover {{
    border-color: var(--accent);
    background: #2b3d4f;
    transform: translateY(-1px);
  }}
  .model-meta {{
    display: flex;
    flex-direction: column;
    gap: 4px;
  }}
  .model-name {{
    font-size: 13.5px;
    font-weight: 600;
    color: var(--text-primary);
  }}
  .model-tags {{
    display: flex;
    gap: 8px;
    align-items: center;
  }}
  .tag {{
    font-size: 11px;
    padding: 2px 7px;
    border-radius: 4px;
  }}
  .tag-coral {{
    background: var(--accent);
    color: #ffffff;
    font-weight: bold;
  }}
  .tag-dim {{
    background: rgba(0,0,0,0.25);
    color: var(--text-secondary);
    border: 1px solid rgba(255,255,255,0.06);
  }}
  .model-badge-active {{
    background: var(--accent);
    color: #ffffff;
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: bold;
  }}
  .model-action-btn {{
    font-size: 12.5px;
    color: var(--text-secondary);
    font-weight: 600;
  }}
  .model-card.inactive:hover .model-action-btn {{
    color: var(--accent);
  }}

  /* Footer */
  .footer {{
    margin-top: 22px;
    font-size: 12.5px;
    color: var(--text-dim);
    line-height: 1.6;
    border-top: 1px solid var(--border);
    padding-top: 14px;
  }}
  .footer code {{
    background: var(--bg-input);
    color: var(--text-primary);
    padding: 2px 6px;
    border-radius: 4px;
  }}

  /* Toast Notification */
  #toast {{
    position: fixed;
    bottom: 24px;
    right: 24px;
    background: var(--bg-card);
    color: var(--text-primary);
    border: 1px solid var(--accent);
    padding: 10px 18px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: bold;
    box-shadow: 0 8px 24px rgba(0,0,0,0.5);
    opacity: 0;
    transform: translateY(10px);
    transition: all 0.25s ease;
    pointer-events: none;
    z-index: 1000;
  }}
  #toast.show {{
    opacity: 1;
    transform: translateY(0);
  }}
</style>
</head>
<body>

<div class="dashboard">
  <!-- Header -->
  <div class="header">
    <div class="header-left">
      <h1>🛡️ LLM 智慧守護代理</h1>
      <div class="sub">石板海軍珊瑚典雅控制儀表 · Windows 本地 AI 推論中樞</div>
    </div>
    <div class="pill-port">
      <span class="pill-dot"></span>
      PORT {PUBLIC_PORT}
    </div>
  </div>

  <!-- Bento Stats Grid -->
  <div class="bento-grid">
    <div class="bento-card">
      <div class="bento-label">🦙 當前載入模型</div>
      <div class="bento-value">
        <code>{cur_model_name}</code>
        <div style="margin-top:6px;font-size:12px;color:var(--text-secondary);">{cur_model_type}</div>
      </div>
    </div>

    <div class="bento-card">
      <div class="bento-label">⚡ 伺服器狀態</div>
      <div class="bento-value">
        {status_badge}
        <div style="margin-top:6px;font-size:12px;color:var(--text-dim);">{strat_desc}</div>
      </div>
    </div>

    <div class="bento-card">
      <div class="bento-label">🔌 推論 API 端點 (OpenAI 相容)</div>
      <div class="bento-value">
        <code id="api-url">http://127.0.0.1:{PUBLIC_PORT}/v1</code>
        <button class="btn-copy" onclick="copyApiUrl()">複製</button>
      </div>
    </div>

    <div class="bento-card">
      <div class="bento-label">📁 模型庫目錄</div>
      <div class="bento-value">
        <code>{MODELS_DIR}</code>
      </div>
    </div>
  </div>

  <!-- Actions Toolbar -->
  <div class="actions-toolbar">
    <a href="/api/wake" class="btn btn-primary">⚡ 立即啟動</a>
    <a href="/api/sleep" class="btn btn-secondary">💤 立即休眠 (釋放顯存)</a>
    <a href="javascript:location.reload()" class="btn btn-secondary">🔄 重新整理</a>
    <a href="/stop" class="btn btn-danger" onclick="return confirm('確定要關閉守護代理與 LLM 嗎？')">🛑 退出守護</a>
  </div>

  <!-- GGUF Models List -->
  <div class="models-section">
    <div class="models-header">
      <span>📦 本地 GGUF 模型庫（點選卡片立即熱切換）</span>
      <span style="font-size:12px;color:var(--text-secondary);">共 {len(state.models)} 個模型</span>
    </div>
    <div class="models-list">
      {model_buttons_html}
    </div>
  </div>

  <!-- Footer Tip -->
  <div class="footer">
    💡 <b>自動按需喚醒</b>：外部翻譯擴充套件、OpenCode 或 Claude 只要向 <code>http://127.0.0.1:{PUBLIC_PORT}/v1</code> 發送推論請求，守護代理即刻於背景自動喚醒並載入模型。
  </div>
</div>

<div id="toast">已複製端點網址！</div>

<script>
  function copyApiUrl() {{
    const url = document.getElementById('api-url').innerText;
    navigator.clipboard.writeText(url).then(() => {{
      const toast = document.getElementById('toast');
      toast.classList.add('show');
      setTimeout(() => toast.classList.remove('show'), 2200);
    }});
  }}

  // 本地即時倒數計時器
  const countdownEl = document.getElementById('countdown-val');
  if (countdownEl) {{
    let sec = parseInt(countdownEl.innerText, 10);
    if (!isNaN(sec) && sec > 0) {{
      const timer = setInterval(() => {{
        sec--;
        if (sec <= 0) {{
          clearInterval(timer);
          countdownEl.innerText = "0";
          setTimeout(() => location.reload(), 1500);
        }} else {{
          countdownEl.innerText = sec;
        }}
      }}, 1000);
    }}
  }}

  // 每 6 秒背景自動輪詢狀態（若休眠則自動刷新狀態）
  setInterval(() => {{
    fetch('/api/status')
      .then(res => res.json())
      .then(data => {{
        // 若伺服器狀態改變則無縫重新載入
        const isRunning = (data.status === 'running');
        const hasPulse = !!document.querySelector('.status-dot.pulse');
        if (isRunning !== hasPulse) {{
          location.reload();
        }}
      }})
      .catch(() => {{}});
  }}, 6000);
</script>

</body>
</html>"""
            body = html.encode("utf-8")
            resp = f"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8") + body
            client_writer.write(resp)
            await client_writer.drain()
            return

        # ── 8. 忽略 favicon 與過濾非 /v1/ 路徑 ──
        if path == "/favicon.ico":
            client_writer.write(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
            await client_writer.drain()
            return

        if not path.startswith("/v1/"):
            client_writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nNot Found\r\n")
            await client_writer.drain()
            return

        # ── 9. 一般推論請求（/v1/...）：自動喚醒並轉發 ──
        # 解析請求中的 model 參數（若有指定且與當前不同則自動切換）
        requested_model = None
        try:
            body_part = header_str.split("\r\n\r\n", 1)[-1] if "\r\n\r\n" in header_str else ""
            if body_part:
                b_json = json.loads(body_part)
                requested_model = b_json.get("model")
        except Exception:
            pass

        if requested_model:
            rm_lower = requested_model.lower()
            target = next((m for m in state.models if rm_lower == m["id"].lower() or rm_lower in m["name"].lower() or m["id"].lower() in rm_lower or ("qwen3vl" in rm_lower and "qwen3vl" in m["id"].lower())), None)
            if target and (not state.current_model or state.current_model["id"] != target["id"]):
                print(f"[⚡ 需求切換] 偵測到請求指定模型: {target['name']}", flush=True)
                await switch_model(target["id"])

        ok = await start_llm()
        if not ok:
            err = b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\n\r\n{\"error\":\"LLM failed to start. Please check llama-server.exe and models.\"}"
            client_writer.write(err)
            await client_writer.drain()
            return

        try:
            llm_reader, llm_writer = await asyncio.open_connection("127.0.0.1", LLM_INTERNAL_PORT)
        except Exception as e:
            err = f"HTTP/1.1 502 Bad Gateway\r\n\r\nCannot connect to LLM internal port: {e}".encode("utf-8")
            client_writer.write(err)
            await client_writer.drain()
            return

        llm_writer.write(initial_data)
        await llm_writer.drain()

        # 雙向串流管線（支援 SSE stream 即時字幕與串流補全）
        async def fwd_client_to_llm():
            try:
                while True:
                    data = await client_reader.read(4096)
                    if not data:
                        break
                    llm_writer.write(data)
                    await llm_writer.drain()
            except Exception:
                pass
            finally:
                try:
                    llm_writer.write_eof()
                except Exception:
                    pass

        async def fwd_llm_to_client():
            try:
                while True:
                    data = await llm_reader.read(4096)
                    if not data:
                        break
                    client_writer.write(data)
                    await client_writer.drain()
            except Exception:
                pass
            finally:
                try:
                    client_writer.close()
                except Exception:
                    pass

        await asyncio.gather(fwd_client_to_llm(), fwd_llm_to_client())

    except Exception as e:
        pass
    finally:
        state.active_requests = max(0, state.active_requests - 1)
        state.last_active_time = time.time()
        try:
            client_writer.close()
        except Exception:
            pass

async def main():
    state.lock = asyncio.Lock()
    state.stop_event = asyncio.Event()

    print("=" * 60)
    print("  🌐 本地 LLM 智慧守護代理 (Windows 專用版) 已啟動")
    print("=" * 60)
    print(f"  • 公共代理端點 : http://127.0.0.1:{PUBLIC_PORT}/v1")
    print(f"  • 網頁控制儀表板 : http://127.0.0.1:{PUBLIC_PORT}/status")
    print(f"  • 模型掃描路徑 : {MODELS_DIR}")
    print(f"  • 推論二進制檔 : {LLAMA_BIN}")
    print("=" * 60)

    init_models()

    server = await asyncio.start_server(handle_proxy_client, "0.0.0.0", PUBLIC_PORT)
    asyncio.create_task(idle_checker())

    try:
        await state.stop_event.wait()
    finally:
        server.close()
        await server.wait_closed()
        stop_llm()
        print("\n[✓ 退出] 守護進程已停止，端口已釋放。")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        stop_llm()
