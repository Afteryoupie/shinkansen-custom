"""
watchdog.config
===============
存放通訊埠、系統路徑、逾時策略與模型分類常數及輔助函式。
"""

import os
import sys
import shutil
import tempfile
from pathlib import Path

# 基本目錄配置
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent

CANDIDATE_MODELS_DIRS = [
    PROJECT_DIR / "models",
    PROJECT_DIR / "Models",
    PROJECT_DIR.parent.parent / "models",
    PROJECT_DIR.parent.parent / "Models",
    PROJECT_DIR.parent / "models",
    PROJECT_DIR.parent / "Models",
    Path(r"C:\LLM_Project\models"),
    Path.cwd() / "models",
    Path.cwd() / "Models",
]
MODELS_DIR = next((d for d in CANDIDATE_MODELS_DIRS if d.exists()), PROJECT_DIR / "models")

# 虛擬環境執行檔路徑 (Windows 為 Scripts, Unix 為 bin)
_venv_sub = "Scripts" if sys.platform == "win32" else "bin"
_py_exe = "python.exe" if sys.platform == "win32" else "python3"
_candidate_venv_dirs = [
    PROJECT_DIR / ".venv" / _venv_sub,
    PROJECT_DIR.parent / ".venv" / _venv_sub,
    PROJECT_DIR.parent.parent / ".venv" / _venv_sub,
    Path(sys.executable).parent,
]
VENV_BIN = next((d for d in _candidate_venv_dirs if (d / _py_exe).exists()), PROJECT_DIR / ".venv" / _venv_sub)

def find_llama_bin() -> Path:
    """跨平台動態尋找 llama-server 執行檔"""
    bin_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    which_bin = shutil.which(bin_name) or shutil.which("llama-server")
    if which_bin:
        return Path(which_bin)

    candidates = [
        Path(r"C:\llama-win-vulkan-x64\llama-server.exe"),
        PROJECT_DIR / bin_name,
        PROJECT_DIR.parent.parent / bin_name,
        PROJECT_DIR.parent / bin_name,
        PROJECT_DIR / "llama" / bin_name,
        PROJECT_DIR / "llama-b10734" / bin_name,
        Path(os.environ.get("LOCALAPPDATA", "")) / "llama-server" / bin_name,
        Path("/opt/homebrew/bin/llama-server"),
        Path("/usr/local/bin/llama-server"),
    ]
    for candidate in candidates:
        if candidate.is_file() and (sys.platform == "win32" or os.access(candidate, os.X_OK)):
            return candidate
    return candidates[0] if (sys.platform == "win32" and candidates[0].is_file()) else (PROJECT_DIR / bin_name if sys.platform == "win32" else Path("/opt/homebrew/bin/llama-server"))

LLAMA_BIN = find_llama_bin()
RAPID_BIN = VENV_BIN / "rapid-mlx"
MLX_BIN = VENV_BIN / "mlx_lm.server"
OMLX_BIN = VENV_BIN / "omlx"

# 網路埠號配置
PUBLIC_PORT = 8080
LLM_INTERNAL_PORT = 8081

# 逾時策略配置（秒）
DEFAULT_IDLE_TIMEOUT = 180    # 模型閒置 3 分鐘自動休眠釋放顯存
DEFAULT_TRANSLATE_IDLE = 180  # 相容別名

# 系統進程紀錄：Windows 使用 %TEMP%，Unix/Mac 保持 /tmp
PID_FILE = (
    Path(tempfile.gettempdir()) / "llm_watchdog.pid"
    if sys.platform == "win32"
    else Path("/tmp/llm_watchdog.pid")
)

def is_translation_model(name: str) -> bool:
    """判斷模型是否為翻譯專用模型（適用閒置休眠策略）"""
    lower = name.lower()
    return any(k in lower for k in ["qwen3vl", "mt", "translat", "hy-mt", "translate"])
