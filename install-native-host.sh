#!/usr/bin/env bash
# install-native-host.sh — 安装 WebRecall Native Messaging Host
#
# 用法：
#   bash install-native-host.sh [EXTENSION_ID]
#
# EXTENSION_ID 可选：若不提供则使用通配符（允许任意已解压扩展调用）
# 安装后在 Chrome 里重新加载插件即可生效。
#
# 支持：macOS（Chrome / Chromium / Brave / Edge）
# 不支持：Windows（需要注册表操作，请参考 Chrome 官方文档）

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
HOST_SCRIPT="$SCRIPT_DIR/native_host.py"
HOST_MANIFEST_TEMPLATE="$SCRIPT_DIR/com.webrecall.native.json"
HOST_NAME="com.webrecall.native"

# ── 参数处理 ────────────────────────────────────────────────────
EXTENSION_ID="${1:-}"

# ── 检查 Python ─────────────────────────────────────────────────
PYTHON="$PROJECT_DIR/backend/venv/bin/python3"
if [ ! -f "$PYTHON" ]; then
  PYTHON="$(which python3 2>/dev/null || which python 2>/dev/null)"
fi
if [ -z "$PYTHON" ]; then
  echo "❌ 未找到 Python，请先安装 Python 3.10+"
  exit 1
fi
echo "✅ 使用 Python：$PYTHON"

# ── 权限 ────────────────────────────────────────────────────────
chmod +x "$HOST_SCRIPT"

# ── 确定 allowed_origins ────────────────────────────────────────
if [ -n "$EXTENSION_ID" ]; then
  ORIGIN="\"chrome-extension://${EXTENSION_ID}/\""
else
  # 通配：安装时不知道 ID，允许用户后续手动修改
  ORIGIN="\"chrome-extension://*/\""
  echo "⚠️  未提供 Extension ID，将使用通配符（允许任意已解压插件调用）"
  echo "   如需精确授权，请把 chrome://extensions 页面的插件 ID 作为参数重新运行："
  echo "   bash install-native-host.sh <你的插件ID>"
fi

# ── 生成最终 manifest ────────────────────────────────────────────
MANIFEST_CONTENT=$(cat "$HOST_MANIFEST_TEMPLATE" \
  | sed "s|__PLACEHOLDER__|$HOST_SCRIPT|g" \
  | sed "s|\"__EXTENSION_ID__\"|$ORIGIN|g")

# ── 安装到各浏览器的 NativeMessagingHosts 目录 ──────────────────
INSTALL_DIRS=()

if [[ "$OSTYPE" == "darwin"* ]]; then
  BASE="$HOME/Library/Application Support"
  INSTALL_DIRS=(
    "$BASE/Google/Chrome/NativeMessagingHosts"
    "$BASE/Google/Chrome Beta/NativeMessagingHosts"
    "$BASE/Google/Chrome Dev/NativeMessagingHosts"
    "$BASE/Chromium/NativeMessagingHosts"
    "$BASE/BraveSoftware/Brave-Browser/NativeMessagingHosts"
    "$BASE/Microsoft Edge/NativeMessagingHosts"
  )
else
  echo "❌ 当前仅支持 macOS。Linux / Windows 用户请参考 Chrome 原生消息传递文档手动安装。"
  exit 1
fi

INSTALLED=0
for DIR in "${INSTALL_DIRS[@]}"; do
  if [ -d "$(dirname "$DIR")" ]; then
    mkdir -p "$DIR"
    echo "$MANIFEST_CONTENT" > "$DIR/$HOST_NAME.json"
    echo "✅ 已安装到：$DIR/$HOST_NAME.json"
    INSTALLED=$((INSTALLED + 1))
  fi
done

if [ "$INSTALLED" -eq 0 ]; then
  echo "❌ 未检测到任何支持的 Chrome 系浏览器目录。"
  echo "   请手动将以下内容保存到对应浏览器的 NativeMessagingHosts 目录："
  echo "$MANIFEST_CONTENT"
  exit 1
fi

echo ""
echo "🎉 Native Messaging Host 安装完成！"
echo "   现在请在 Chrome 的 chrome://extensions 页面重新加载 WebRecall 插件，"
echo "   然后点击插件弹窗中「用法」标签下的「启动」按钮即可自动启动 Lite Server。"
