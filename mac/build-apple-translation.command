#!/bin/bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backends/apple-intelligence-api"
REVISION="40083e051488dca6eddbb8507052dd22d079c610"
if [[ ! -d "$BACKEND_DIR" ]]; then
  mkdir -p "$PROJECT_DIR/backends"
  git clone https://github.com/gouwsxander/Apple-Intelligence-API.git "$BACKEND_DIR"
  git -C "$BACKEND_DIR" checkout --detach "$REVISION"
fi
cd "$BACKEND_DIR"
PATCH_FILE="$PROJECT_DIR/mac/apple-api-body-limit.patch"
if git apply --check "$PATCH_FILE" 2>/dev/null; then
  git apply "$PATCH_FILE"
elif ! git apply --reverse --check "$PATCH_FILE" 2>/dev/null; then
  echo "Apple API 請求大小修正無法套用，請檢查上游版本。" >&2
  exit 1
fi
xcrun swift build -c release
echo "Apple 翻譯後端已建置完成。請重新啟動LLM watchdog並選取 Apple Intelligence（新幹線翻譯）。"
