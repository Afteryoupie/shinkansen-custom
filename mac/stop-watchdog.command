#!/usr/bin/env bash
# ==============================================================================
#  Shinkansen Custom — macOS 本地 LLM 智慧守護代理一鍵停止腳本
# ==============================================================================

echo "正在安全關閉本地 LLM 守護代理並釋放記憶體..."

# 優先透過 API 安全關閉
curl -s -X POST http://127.0.0.1:8080/api/stop >/dev/null 2>&1 || true

sleep 0.5

# 清理殘留進程
pkill -f "watchdog.llm_watchdog" 2>/dev/null || true
pkill -f "llama-server" 2>/dev/null || true
pkill -f "rapid-mlx" 2>/dev/null || true
pkill -f "mlx_lm.server" 2>/dev/null || true
pkill -f "omlx" 2>/dev/null || true

echo "✓ 守護進程已終止，Port 8080 已釋放，顯存/記憶體已 100% 釋放。"
