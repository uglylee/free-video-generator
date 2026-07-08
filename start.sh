#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "================================================"
echo "  Agnes Video Generator"
echo "================================================"
echo ""

# ── L5: 环境校验 ──────────────────────────────────────────────

# 检查 Python 3.10+
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 python3，请先安装 Python 3.10+"
    echo "   macOS:   brew install python3"
    echo "   Ubuntu:  sudo apt install python3 python3-venv"
    exit 1
fi

python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null || {
    PY_VER=$(python3 --version 2>&1)
    echo "❌ Python 版本过低 ($PY_VER)，需要 3.10+"
    exit 1
}

# 检查 ffmpeg（视频拼接和音频处理依赖）
if ! command -v ffmpeg &> /dev/null; then
    echo "❌ 未找到 ffmpeg，视频处理依赖 ffmpeg"
    echo "   macOS:   brew install ffmpeg"
    echo "   Ubuntu:  sudo apt install ffmpeg"
    exit 1
fi

# 检查端口 8765 是否被占用
if command -v lsof &> /dev/null; then
    PID=$(lsof -ti:8765 2>/dev/null || true)
    if [ -n "$PID" ]; then
        echo "⚠️  端口 8765 已被 PID $PID 占用"
        echo "   执行: kill $PID 后重试，或修改端口"
        exit 1
    fi
fi

echo "✓ 环境检查通过"
echo ""

VENV_DIR=".venv"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "[1/3] 创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi

echo "[2/3] 安装依赖..."
$VENV_PIP install -q -r requirements.txt

echo "[3/3] 启动服务..."
echo ""
echo "  浏览器将自动打开 http://localhost:8765"
echo "  按 Ctrl+C 停止服务"
echo ""

sleep 1

if command -v open &> /dev/null; then
    (sleep 1.5 && open http://localhost:8765) &
elif command -v xdg-open &> /dev/null; then
    (sleep 1.5 && xdg-open http://localhost:8765) &
fi

$VENV_PYTHON server.py
