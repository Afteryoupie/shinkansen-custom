"""
watchdog.dashboard
==================
負責載入並渲染 Web 控制儀表板 HTML。
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional
from watchdog.config import PUBLIC_PORT

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "dashboard.html"
_cached_template: Optional[str] = None

def get_template() -> str:
    """取得儀表板 HTML 範本"""
    if not TEMPLATE_PATH.is_file():
        raise FileNotFoundError(f"找不到控制台前端範本檔案: {TEMPLATE_PATH}")
    return TEMPLATE_PATH.read_text(encoding="utf-8")

def render_dashboard(initial_state: Dict[str, Any], public_port: int = PUBLIC_PORT) -> str:
    """將執行時狀態與通訊埠渲染進 HTML 範本"""
    template = get_template()
    json_str = json.dumps(initial_state, ensure_ascii=False)
    return template.replace("__INITIAL_STATE_JSON__", json_str).replace("__PUBLIC_PORT__", str(public_port))
