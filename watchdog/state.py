"""
watchdog.state
==============
集中管理守護代理與本地 LLM 的全域執行狀態。
"""

import time
import asyncio
from typing import Optional, List, Dict, Any

class State:
    """守護進程與推論引擎執行時期狀態容器"""
    def __init__(self):
        self.llm_proc = None
        self.last_active_time: float = time.time()
        self.active_requests: int = 0
        self.is_starting: bool = False
        self.current_model: Optional[Dict[str, Any]] = None
        self.models: List[Dict[str, Any]] = []
        self.lock: Optional[asyncio.Lock] = None
        self.stop_event: Optional[asyncio.Event] = None
        self.should_exit: bool = False
        self.auto_sleep_enabled: bool = True

# 全域單例
state = State()
