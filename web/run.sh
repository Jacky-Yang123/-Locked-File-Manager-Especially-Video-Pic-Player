#!/bin/bash
# Locked Video Player - Web Edition Launcher
cd "$(dirname "$0")"

echo "═══════════════════════════════════════"
echo "  🔒 Locked Video Player - Web Edition"
echo "═══════════════════════════════════════"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未安装，请先安装 Python 3.8+"
    exit 1
fi

# Create venv if needed
if [ ! -d "venv" ]; then
    echo "📦 首次运行，创建虚拟环境..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies
echo "📦 检查依赖..."
pip install -q -r requirements.txt

echo ""
echo "🚀 启动服务..."
python3 app.py
