#!/bin/bash
# =============================================================================
# RAF Intelligence — Safe Local Dev Startup
# Prevents system freezes by controlling resource usage
# =============================================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

echo "============================================"
echo "  RAF Intelligence — Starting Dev Server"
echo "============================================"
echo ""

# --- Kill any existing RAF processes ---
echo "[1/5] Cleaning up old processes..."
pkill -f "uvicorn app.main" 2>/dev/null || true
pkill -f "next dev" 2>/dev/null || true
sleep 1

# --- Check system resources ---
echo "[2/5] Checking system resources..."
FREE_MEM=$(vm_stat | awk '/Pages free/ {gsub(/\./,"",$3); print int($3 * 16384 / 1024 / 1024 / 1024)}')
echo "  Free memory: ~${FREE_MEM}GB"
if [ "$FREE_MEM" -lt 2 ]; then
    echo "  ⚠️  WARNING: Less than 2GB free memory!"
    echo "  Close unused apps before continuing."
    echo "  Press Enter to continue anyway, or Ctrl+C to abort."
    read
fi

# --- Start Backend (lightweight mode) ---
echo "[3/5] Starting backend on :8500..."
cd "$BACKEND_DIR"
# NO --reload flag (prevents file watcher CPU spike)
# Single worker, low concurrency
python3 -m uvicorn app.main:app \
    --host 127.0.0.1 \
    --port 8500 \
    --workers 1 \
    --limit-concurrency 20 \
    --timeout-keep-alive 10 \
    --log-level warning \
    2>&1 | tee /tmp/raf_backend.log &
BACKEND_PID=$!
echo "  Backend PID: $BACKEND_PID"

# Wait for backend to be ready
sleep 3
if curl -s -o /dev/null -w "" http://localhost:8500/health 2>/dev/null; then
    echo "  ✅ Backend ready"
else
    echo "  ⚠️  Backend started (DB may not be connected)"
fi

# --- Start Frontend (controlled mode) ---
echo "[4/5] Starting frontend on :3000..."
cd "$FRONTEND_DIR"
# NODE_OPTIONS limits Node.js memory to 1GB (prevents runaway usage)
NODE_OPTIONS="--max-old-space-size=1024" npm run dev 2>&1 | tee /tmp/raf_frontend.log &
FRONTEND_PID=$!
echo "  Frontend PID: $FRONTEND_PID"

sleep 5
echo "  ✅ Frontend starting..."

# --- Summary ---
echo ""
echo "[5/5] Done!"
echo "============================================"
echo "  Frontend:  http://localhost:3000"
echo "  Backend:   http://localhost:8500"
echo "  API Docs:  http://localhost:8500/docs"
echo ""
echo "  Backend log:  /tmp/raf_backend.log"
echo "  Frontend log: /tmp/raf_frontend.log"
echo ""
echo "  To stop:  pkill -f 'uvicorn app.main'; pkill -f 'next dev'"
echo "============================================"

# Keep script running so Ctrl+C kills both
wait
