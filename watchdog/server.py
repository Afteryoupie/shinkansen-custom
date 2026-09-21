"""
watchdog.server
===============
處理 8080 端口的代理請求、REST API 路由、Web 控制儀表板，
以及 8765 端口的向後相容喚醒伺服器。
"""

import sys
import time
import json
import asyncio
import urllib.parse
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from watchdog.config import PUBLIC_PORT, LLM_INTERNAL_PORT
from watchdog.state import state
from watchdog.manager import scan_models, start_llm, stop_llm, switch_model
from watchdog.dashboard import render_dashboard

async def handle_proxy_client(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter):
    """處理來自瀏覽器插件、AI 開發工具或 Web 儀表板的請求"""
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

        # 0. GET /health or /api/health：健康檢查端點
        if path in ("/health", "/api/health") and method == "GET":
            llm_alive = state.llm_proc and state.llm_proc.poll() is None
            payload = {
                "status": "ok",
                "llm_status": "running" if llm_alive else ("starting" if state.is_starting else "sleeping"),
                "current_model": state.current_model["name"] if state.current_model else "",
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

        # 1. GET /api/status：回傳當前狀態與模型列表（供 Swift Menu Bar 輪詢）
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
                elapsed = time.time() - state.last_active_time
                rem = max(0, int(timeout - elapsed))
                if elapsed >= timeout and state.auto_sleep_enabled and state.active_requests == 0:
                    stop_llm()
                    status_str = "sleeping"
                    rem = 0
            else:
                rem = 0

            payload = {
                "status": status_str,
                "current_model": m["name"] if m else "",
                "current_model_id": m["id"] if m else "",
                "is_translation": m.get("is_translation", False) if m else False,
                "idle_timeout": timeout,
                "idle_remaining": rem,
                "auto_sleep_enabled": state.auto_sleep_enabled,
                "active_requests": state.active_requests,
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

            is_html_nav = method == "GET" and "text/html" in header_str and "application/json" not in header_str

            if not target_model:
                body = json.dumps({"error": "缺少 model 參數"}).encode("utf-8")
                resp = f"HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8") + body
            else:
                ok, msg = await switch_model(target_model)
                if is_html_nav:
                    resp = b"HTTP/1.1 303 See Other\r\nLocation: /status\r\nConnection: close\r\n\r\n"
                    client_writer.write(resp)
                    await client_writer.drain()
                    return
                body = json.dumps({"status": "ok" if ok else "error", "message": msg, "current_model": state.current_model["name"]}).encode("utf-8")
                resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8") + body
            client_writer.write(resp)
            await client_writer.drain()
            return

        # 3. POST /api/sleep：立即休眠釋放顯存
        if path == "/api/sleep" and method in ("POST", "GET"):
            stop_llm()
            is_html_nav = method == "GET" and "text/html" in header_str and "application/json" not in header_str
            if is_html_nav:
                resp = b"HTTP/1.1 303 See Other\r\nLocation: /status\r\nConnection: close\r\n\r\n"
                client_writer.write(resp)
                await client_writer.drain()
                return
            body = json.dumps({"status": "ok", "state": "sleeping"}).encode("utf-8")
            resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8") + body
            client_writer.write(resp)
            await client_writer.drain()
            return

        # 3.5. POST /api/toggle_auto_sleep 或 /api/auto_sleep：切換自動休眠開關
        if path in ("/api/toggle_auto_sleep", "/api/auto_sleep") and method in ("POST", "GET"):
            if "enabled" in query_params:
                val = query_params["enabled"][0].lower()
                state.auto_sleep_enabled = val in ("1", "true", "yes", "on")
            else:
                state.auto_sleep_enabled = not state.auto_sleep_enabled

            is_html_nav = method == "GET" and "text/html" in header_str and "application/json" not in header_str
            if is_html_nav:
                resp = b"HTTP/1.1 303 See Other\r\nLocation: /status\r\nConnection: close\r\n\r\n"
                client_writer.write(resp)
                await client_writer.drain()
                return
            body = json.dumps({"status": "ok", "auto_sleep_enabled": state.auto_sleep_enabled}).encode("utf-8")
            resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8") + body
            client_writer.write(resp)
            await client_writer.drain()
            return

        # 4. POST /api/wake 或 /api/start：手動喚醒
        if path in ("/api/wake", "/api/start") and method in ("POST", "GET"):
            ok = await start_llm()
            is_html_nav = method == "GET" and "text/html" in header_str and "application/json" not in header_str
            if is_html_nav:
                resp = b"HTTP/1.1 303 See Other\r\nLocation: /status\r\nConnection: close\r\n\r\n"
                client_writer.write(resp)
                await client_writer.drain()
                return
            body = json.dumps({"status": "ok" if ok else "error", "state": "running" if ok else "failed"}).encode("utf-8")
            resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8") + body
            client_writer.write(resp)
            await client_writer.drain()
            return

        # 5. POST /api/stop 或 GET /stop：完全停止
        if path in ("/api/stop", "/stop", "/shutdown"):
            stop_llm()
            state.should_exit = True
            body = b'{"status":"stopped"}' if path.startswith("/api") else "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>守護進程已停止</title><style>body{font-family:Segoe UI,-apple-system,BlinkMacSystemFont,sans-serif;background:#1c2833;color:#DCDDD8;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;} .box{background:#273746;border:1px solid #475F77;border-top:3.5px solid #D74B4B;padding:36px;border-radius:14px;text-align:center;box-shadow:0 20px 45px rgba(0,0,0,0.5);max-width:480px;} h1{color:#D74B4B;font-size:20px;margin-bottom:12px;} p{color:#9cb1c4;font-size:14px;line-height:1.6;}</style></head><body><div class=\"box\"><h1>🛑 LLM 守護代理已完全關閉</h1><p>顯存與系統記憶體已 100% 釋放，您可以安心關閉此分頁。</p></div></body></html>".encode("utf-8")
            ct = "application/json" if path.startswith("/api") else "text/html; charset=utf-8"
            resp = f"HTTP/1.1 200 OK\r\nContent-Type: {ct}\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8") + body
            client_writer.write(resp)
            await client_writer.drain()
            if state.stop_event:
                asyncio.get_event_loop().call_later(0.3, state.stop_event.set)
            return

        # 6. GET /v1/models：標準 OpenAI 相容模型清單 (不喚醒內核，秒回)
        if (path == "/v1/models" or path == "/v1/models/") and method == "GET":
            state.models = scan_models()
            model_items = []
            for m in state.models:
                model_items.append({"id": m["id"], "object": "model", "created": 1700000000, "owned_by": "local-llm"})
                model_items.append({"id": m["path"], "object": "model", "created": 1700000000, "owned_by": "local-llm"})
            model_items.append({"id": "default", "object": "model", "created": 1700000000, "owned_by": "local-llm"})
            
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

        if path.startswith("/v1/models/") and method == "GET":
            m_id = urllib.parse.unquote(path[len("/v1/models/"):].strip("/"))
            body = json.dumps({"id": m_id, "object": "model", "created": 1700000000, "owned_by": "local-llm"}, ensure_ascii=False).encode("utf-8")
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
            if state.is_starting:
                status_str = "starting"
            elif llm_alive:
                status_str = "running"
            else:
                status_str = "sleeping"

            m = state.current_model
            timeout = m.get("idle_timeout", 0) if m else 0
            if llm_alive and timeout > 0:
                elapsed = time.time() - state.last_active_time
                rem = max(0, int(timeout - elapsed))
                if elapsed >= timeout and state.auto_sleep_enabled and state.active_requests == 0:
                    stop_llm()
                    status_str = "sleeping"
                    rem = 0
            else:
                rem = 0

            initial_state = {
                "status": status_str,
                "current_model": m["name"] if m else "",
                "current_model_id": m["id"] if m else "",
                "is_translation": m.get("is_translation", False) if m else False,
                "idle_timeout": timeout,
                "idle_remaining": rem,
                "auto_sleep_enabled": state.auto_sleep_enabled,
                "models": state.models,
            }

            html = render_dashboard(initial_state, PUBLIC_PORT)
            body = html.encode("utf-8")
            resp = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: text/html; charset=utf-8\r\n"
                f"Access-Control-Allow-Origin: *\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("utf-8") + body
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
        state.active_requests += 1
        state.last_active_time = time.time()
        try:
            ok = await start_llm()
            if not ok:
                err = b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"error\":\"LLM failed to start\"}"
                client_writer.write(err)
                await client_writer.drain()
                return

            # 智慧正規化請求 Body 中的 model 名稱（適用於 rapid-mlx / omlx / llama-server）
            header_bytes, sep, body_bytes = initial_data.partition(b"\r\n\r\n")
            if sep:
                cl_val = None
                for line in header_bytes.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        try:
                            cl_val = int(line.split(b":", 1)[1].strip())
                        except Exception:
                            pass
                        break
                if cl_val is not None and len(body_bytes) < cl_val:
                    while len(body_bytes) < cl_val:
                        chunk = await client_reader.read(min(4096, cl_val - len(body_bytes)))
                        if not chunk:
                            break
                        body_bytes += chunk

                if b"application/json" in header_bytes and b'"model"' in body_bytes and state.current_model:
                    try:
                        data_obj = json.loads(body_bytes.decode("utf-8"))
                        if state.current_model["type"] == "mlx":
                            data_obj["model"] = state.current_model["path"]
                        elif state.current_model["type"] == "omlx":
                            data_obj["model"] = state.current_model["id"]
                        elif state.current_model["type"] == "gguf":
                            data_obj["model"] = state.current_model["path"]
                        body_bytes = json.dumps(data_obj).encode("utf-8")
                    except Exception:
                        pass

                new_headers = []
                has_conn = False
                for line in header_bytes.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        new_headers.append(f"Content-Length: {len(body_bytes)}".encode("utf-8"))
                    elif line.lower().startswith(b"connection:"):
                        new_headers.append(b"Connection: close")
                        has_conn = True
                    else:
                        new_headers.append(line)
                if not has_conn:
                    new_headers.append(b"Connection: close")

                initial_data = b"\r\n".join(new_headers) + b"\r\n\r\n" + body_bytes

            try:
                llm_reader, llm_writer = await asyncio.open_connection("127.0.0.1", LLM_INTERNAL_PORT)
            except Exception as e:
                err = f"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\nCannot connect to LLM: {e}".encode("utf-8")
                client_writer.write(err)
                await client_writer.drain()
                return

            llm_writer.write(initial_data)
            await llm_writer.drain()

            # 雙向串流轉發（支援 SSE stream 即時字幕與串流補全）
            async def fwd_client_to_llm():
                try:
                    while True:
                        data = await client_reader.read(4096)
                        if not data:
                            break
                        llm_writer.write(data)
                        await llm_writer.drain()
                except (asyncio.CancelledError, Exception):
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
                except (asyncio.CancelledError, Exception):
                    pass

            t_client = asyncio.create_task(fwd_client_to_llm())
            t_llm = asyncio.create_task(fwd_llm_to_client())

            # LLM 傳送完回應 (t_llm 完成) 或客戶端斷開 (t_client 完成) 即結束
            done, pending = await asyncio.wait([t_client, t_llm], return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

            try:
                llm_writer.close()
                await llm_writer.wait_closed()
            except Exception:
                pass
        finally:
            state.active_requests = max(0, state.active_requests - 1)
            state.last_active_time = time.time()

    except Exception:
        pass
    finally:
        client_writer.close()
        try:
            await client_writer.wait_closed()
        except Exception:
            pass
