#!/usr/bin/env bash
# ==============================================================================
#  Shinkansen Custom — macOS 本地 LLM 智慧守護代理一鍵啟動腳本
# ==============================================================================

DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

# 若存在虛擬環境則優先啟用
if [ -d ".venv" ]; then
    source .venv/bin/activate 2>/dev/null || true
elif [ -d "../.venv" ]; then
    source ../.venv/bin/activate 2>/dev/null || true
fi

echo "============================================================"
echo "  🚄 Shinkansen Custom (macOS) 本地 LLM 守護代理正在啟動..."
echo "============================================================"

# 背景啟動 Python watchdog 模組
python3 -m watchdog.llm_watchdog &

sleep 0.8

# 自動開啟控制儀表板
if command -v open >/dev/null 2>&1; then
    open "http://127.0.0.1:8080/status"
fi

echo "✓ 守護代理已在背景執行 (Port 8080)。"
echo "  • 網頁儀表板: http://127.0.0.1:8080/status"
echo "  • 若要關閉守護，請執行 mac/stop-watchdog.command"
echo "============================================================"
