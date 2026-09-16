#!/usr/bin/env python3
"""
🌐 本地 LLM 智慧守護代理 (Smart Watchdog & Model Switcher)
- 常駐監聽 8080（推論請求代理與 API 控制）
- 待命狀態僅佔用 ~15MB RAM、0.0% CPU
- 自動動態掃描 ~/LLM/Models 下的所有模型 (MLX 與 GGUF)
- 全模型預設閒置 3 分鐘自動休眠，100% 釋放 GPU 顯存與記憶體
- 支援 REST API (/api/status, /api/switch, /api/sleep, /api/wake, /api/stop)
- 自動正規化 /v1/chat/completions 中的 model 名稱，外接 AI 工具免打冗長路徑
- 配合原生系統列 (Tray / MenuBar) 達成極簡狀態顯示與一鍵切換
"""

import sys
import os
import signal
import asyncio
from pathlib import Path

# 解決 Windows 命令提示字元預設 CP950 編碼導致 Emoji 拋出 UnicodeEncodeError 的問題
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 確保可正確引用 watchdog 套件（將專案根目錄加入 sys.path）
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from watchdog.config import (
    PUBLIC_PORT,
    PID_FILE,
)
from watchdog.state import state
from watchdog.manager import (
    init_models,
    stop_llm,
    idle_checker,
)
from watchdog.server import (
    handle_proxy_client,
)

def cleanup():
    """清理退出處理：停止 LLM 並刪除 PID 檔"""
    print("\n[🛑 關閉] 正在關閉守護進程與 LLM...", flush=True)
    stop_llm()
    if PID_FILE.exists():
        try:
            PID_FILE.unlink()
        except Exception:
            pass
    print("[✓ 完成] 守護進程已退出。\n", flush=True)

async def main():
    state.lock = asyncio.Lock()
    init_models()

    PID_FILE.write_text(str(os.getpid()))

    for arg in sys.argv[1:]:
        if arg.startswith("--idle="):
            try:
                custom_idle = int(arg.split("=")[1])
                for m in state.models:
                    m["idle_timeout"] = custom_idle
            except Exception:
                pass

    print("=" * 65)
    print("  🌐  LLM 智慧守護代理與模型切換中樞 (Smart Watchdog Proxy)")
    print("=" * 65)
    cur_name = state.current_model["name"] if state.current_model else "無"
    print(f"  預設模型    : {cur_name}")
    print(f"  公共端點    : http://127.0.0.1:{PUBLIC_PORT}/v1 (所有 AI 工具通用)")
    print(f"  狀態儀表板  : http://127.0.0.1:{PUBLIC_PORT}/status")
    print(f"  REST API    : http://127.0.0.1:{PUBLIC_PORT}/api/status")
    print(f"  目前狀態    : ⚪ 待命中 (RAM 僅 ~15MB，請求抵達或選單切換時秒級啟動)")
    print("-" * 65)
    print(f"  已掃描模型 ({len(state.models)} 個):")
    for m in state.models:
        timeout = m.get("idle_timeout", 0)
        mode = f"{timeout // 60}分鐘自動休眠" if timeout > 0 else "常駐不休眠"
        print(f"    • [{m['type'].upper()}] {m['name']} ({mode})")
    print("=" * 65)

    server_8080 = await asyncio.start_server(handle_proxy_client, "127.0.0.1", PUBLIC_PORT)

    stop_event = asyncio.Event()
    state.stop_event = stop_event

    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
    else:
        def _win_sig_handler(signum, frame):
            print("\n[系統] 收到終止信號，正在退出...", flush=True)
            stop_event.set()
        signal.signal(signal.SIGINT, _win_sig_handler)
        signal.signal(signal.SIGTERM, _win_sig_handler)

    asyncio.create_task(idle_checker())

    async with server_8080:
        while not stop_event.is_set():
            await asyncio.sleep(0.5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        cleanup()
