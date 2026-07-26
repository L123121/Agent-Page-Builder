#!/bin/bash
# 低代码平台 — 一键启动脚本（macOS/Linux）
# 使用方式：chmod +x start.sh && ./start.sh

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo "   低代码平台 — 启动中..."
echo "============================================"

# 启动后端
echo ""
echo "[1/2] 启动后端 (FastAPI)..."
cd "$ROOT_DIR/backend"
if [ -d "venv" ]; then
    source venv/bin/activate
fi
uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# 启动前端
echo "[2/2] 启动前端 (Vite)..."
cd "$ROOT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "============================================"
echo "   启动完成！"
echo "============================================"
echo ""
echo "前端编辑器: http://localhost:5173"
echo "后端 API:    http://localhost:8000"
echo "API 文档:    http://localhost:8000/docs"
echo ""
echo "按 Ctrl+C 终止服务"

# 捕获 Ctrl+C 并终止子进程
trap "echo '正在停止服务...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" SIGINT SIGTERM

# 等待任一进程退出
wait