#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM Watchdog 系統列圖示
- 綠色 LLM 圖示：llama-server 運行中
- 白色 LLM 圖示：llama-server 休眠中（待命）
- 右鍵選單：開啟儀表板、啟動/休眠模型、退出守護代理
輪詢 http://127.0.0.1:8080/api/status 取得狀態。
"""

import threading
import time
import sys
import urllib.request
import urllib.error
import json
import subprocess
import webbrowser
import urllib.parse

try:
    from PIL import Image, ImageDraw, ImageFont
    import pystray
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "pystray", "Pillow", "-q"])
    from PIL import Image, ImageDraw, ImageFont
    import pystray

API_BASE = "http://127.0.0.1:8080"
POLL_INTERVAL = 3  # 秒

# ────────────────────────────────────────────────────
#  圖示生成：LLM 字樣 + 狀態燈
# ────────────────────────────────────────────────────

def _make_icon(running: bool, starting: bool = False) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 背景圓形（石板海軍珊瑚配色調和）
    if starting:
        bg_color = (215, 75, 75, 235)   # 珊瑚朱紅：啟動載入中 (#D74B4B)
    elif running:
        bg_color = (74, 222, 128, 235)  # 翠綠：運行中 (#4ade80)
    else:
        bg_color = (71, 95, 119, 220)   # 鋼青藍灰：待命顯存釋放 (#475F77)

    draw.ellipse([2, 2, size - 2, size - 2], fill=bg_color)

    # 繪製「LLM」字樣（象牙暖白）
    text = "LLM"
    text_color = (255, 255, 255, 255) if (running or starting) else (220, 221, 216, 255)
    try:
        font = ImageFont.truetype("arialbd.ttf", 18)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((size - tw) // 2, (size - th) // 2 - 2), text, fill=text_color, font=font)

    # 狀態指示小圓點（右下角）
    dot_color = (74, 222, 128) if running else ((215, 75, 75) if starting else (156, 177, 196))
    draw.ellipse([size - 18, size - 18, size - 4, size - 4], fill=dot_color, outline=(28, 40, 51, 180))

    return img


# ────────────────────────────────────────────────────
#  API 查詢
# ────────────────────────────────────────────────────

def api_get(path: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{API_BASE}{path}", timeout=2) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def api_post(path: str) -> dict | None:
    try:
        req = urllib.request.Request(f"{API_BASE}{path}", method="POST", data=b"")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


# ────────────────────────────────────────────────────
#  系統列應用程式
# ────────────────────────────────────────────────────

class LLMTray:
    def __init__(self):
        self._status = "offline"  # offline / sleeping / starting / running
        self._model_name = ""
        self._models = []
        self._lock = threading.Lock()

        # 建立 pystray 圖示
        self._tray = pystray.Icon(
            name="llm_watchdog",
            icon=_make_icon(False),
            title="LLM 守護代理（待命中）",
            menu=self._build_menu()
        )

    # ── 選單建立 ──────────────────────────────────────

    def _build_menu(self):
        with self._lock:
            models = list(self._models)

        # 模型次選單項目（純文字，點選即切換並啟動）
        if models:
            model_items = [
                pystray.MenuItem(
                    m["name"],
                    self._make_switch_handler(m["id"])
                )
                for m in models
            ]
        else:
            model_items = [
                pystray.MenuItem("(尚未偵測到模型)", None, enabled=False)
            ]

        return pystray.Menu(
            pystray.MenuItem("開啟控制儀表板", self._open_dashboard),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "切換並啟動模型",
                pystray.Menu(*model_items)
            ),
            pystray.MenuItem("立即休眠釋放顯存", self._sleep_model),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("重新整理狀態", self._refresh_now),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出守護代理", self._quit),
        )

    def _make_switch_handler(self, model_id: str):
        """為每個模型產生獨立的點擊處理函式"""
        def handler(icon=None, item=None):
            threading.Thread(target=self._do_switch, args=(model_id,), daemon=True).start()
        return handler

    def _do_switch(self, model_id: str):
        try:
            url = f"{API_BASE}/api/switch?model={urllib.parse.quote(model_id)}"
            req = urllib.request.Request(url, method="POST", data=b"")
            with urllib.request.urlopen(req, timeout=60) as resp:
                pass
        except Exception:
            pass
        time.sleep(0.5)
        self._refresh_state()

    # ── 狀態輪詢（背景執行緒）────────────────────────

    def _poll_loop(self):
        while True:
            self._refresh_state()
            time.sleep(POLL_INTERVAL)

    def _refresh_state(self):
        data = api_get("/api/status")
        with self._lock:
            if data is None:
                self._status = "offline"
                self._model_name = ""
                self._models = []
            else:
                self._status = data.get("status", "sleeping")
                self._model_name = data.get("current_model", "")
                self._models = data.get("models", [])
        self._update_icon()
        # 每次狀態更新也重建選單（模型清單可能改變）
        try:
            self._tray.menu = self._build_menu()
        except Exception:
            pass

    def _update_icon(self):
        with self._lock:
            status = self._status
            model = self._model_name

        running   = (status == "running")
        starting  = (status == "starting")
        offline   = (status == "offline")

        new_icon = _make_icon(running, starting)

        if offline:
            tip = "LLM 守護代理（未啟動）"
        elif starting:
            tip = f"LLM 守護代理 啟動中：{model}"
        elif running:
            tip = f"LLM 守護代理 運行中：{model}"
        else:
            tip = "LLM 守護代理 待命（顯存已釋放）"

        self._tray.icon = new_icon
        self._tray.title = tip

    # ── 動作 ─────────────────────────────────────────

    def _open_dashboard(self, icon=None, item=None):
        webbrowser.open(f"{API_BASE}/status")

    def _wake_model(self, icon=None, item=None):
        api_post("/api/wake")
        time.sleep(0.5)
        self._refresh_state()

    def _sleep_model(self, icon=None, item=None):
        api_post("/api/sleep")
        time.sleep(0.5)
        self._refresh_state()

    def _refresh_now(self, icon=None, item=None):
        self._refresh_state()

    def _quit(self, icon=None, item=None):
        api_post("/api/stop")
        self._tray.stop()

    # ── 啟動 ──────────────────────────────────────────

    def run(self):
        # 背景輪詢執行緒
        t = threading.Thread(target=self._poll_loop, daemon=True)
        t.start()
        # 主執行緒跑 pystray（pystray 必須在主執行緒）
        self._tray.run()


# ────────────────────────────────────────────────────
#  進入點
# ────────────────────────────────────────────────────

if __name__ == "__main__":
    LLMTray().run()
