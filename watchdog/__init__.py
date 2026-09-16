"""
LLM Smart Watchdog & Model Switcher Package
"""

from watchdog.config import (
    PUBLIC_PORT,
    LLM_INTERNAL_PORT,
    DEFAULT_TRANSLATE_IDLE,
    PID_FILE,
)
from watchdog.state import state, State
from watchdog.manager import (
    scan_models,
    init_models,
    start_llm,
    stop_llm,
    switch_model,
    idle_checker,
)
from watchdog.server import handle_proxy_client

__all__ = [
    "PUBLIC_PORT",
    "LLM_INTERNAL_PORT",
    "DEFAULT_TRANSLATE_IDLE",
    "PID_FILE",
    "state",
    "State",
    "scan_models",
    "init_models",
    "start_llm",
    "stop_llm",
    "switch_model",
    "idle_checker",
    "handle_proxy_client",
]
