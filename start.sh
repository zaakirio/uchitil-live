#!/bin/bash
set -e

# Uchitil Live - Local Development Launcher
# Usage: ./start.sh [backend|frontend|all]

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_LOG="/tmp/uchitil-live-backend.log"
FRONTEND_LOG="/tmp/uchitil-live-frontend.log"

# The .app bundle path (created by tauri build --debug)
APP_BUNDLE="$ROOT_DIR/target/debug/bundle/macos/Uchitil Live.app"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[Uchitil Live]${NC} $1"; }
success() { echo -e "${GREEN}[Uchitil Live]${NC} $1"; }
warn() { echo -e "${YELLOW}[Uchitil Live]${NC} $1"; }
error() { echo -e "${RED}[Uchitil Live]${NC} $1"; }

cleanup() {
    log "Shutting down..."
    if [ -n "$BACKEND_PID" ]; then
        kill "$BACKEND_PID" 2>/dev/null && log "Backend stopped"
    fi
    if [ -n "$APP_PID" ]; then
        kill "$APP_PID" 2>/dev/null && log "App stopped"
    fi
    # Also kill the app by bundle name
    pkill -f "Uchitil Live.app" 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

check_ollama() {
    if ! command -v ollama &>/dev/null; then
        warn "Ollama not found. LLM summarization won't work."
        warn "Install: https://ollama.com/download"
        return 1
    fi

    if ! curl -s http://localhost:11434/api/tags &>/dev/null; then
        log "Starting Ollama..."
        open -a Ollama 2>/dev/null || ollama serve &>/dev/null &
        sleep 3
    fi

    # Check if recommended model is available
    if ! ollama list 2>/dev/null | grep -q "llama3.1:8b"; then
        warn "Recommended model 'llama3.1:8b' not found."
        warn "Pull it with: ollama pull llama3.1:8b"
    else
        success "Ollama ready with llama3.1:8b"
    fi
}

start_backend() {
    log "Starting backend (FastAPI + MongoDB)..."

    # Check for venv
    if [ ! -d "$BACKEND_DIR/venv" ]; then
        log "Creating Python virtual environment..."
        python3.13 -m venv "$BACKEND_DIR/venv"
        source "$BACKEND_DIR/venv/bin/activate"
        pip install -q -r "$BACKEND_DIR/requirements.txt"
    else
        source "$BACKEND_DIR/venv/bin/activate"
    fi

    # Check .env
    if [ ! -f "$BACKEND_DIR/.env" ]; then
        error "No .env file found! Copy .env.example and configure:"
        error "  cp backend/.env.example backend/.env"
        return 1
    fi

    cd "$BACKEND_DIR"
    python app/main.py > "$BACKEND_LOG" 2>&1 &
    BACKEND_PID=$!

    # Wait for startup
    for i in $(seq 1 15); do
        if curl -s http://localhost:5167/get-sessions &>/dev/null; then
            success "Backend running at http://localhost:5167"
            success "API docs at http://localhost:5167/docs"
            return 0
        fi
        sleep 1
    done

    error "Backend failed to start. Check logs: tail -50 $BACKEND_LOG"
    return 1
}

start_frontend() {
    log "Building and launching frontend as .app bundle..."
    log "(Required for macOS Sequoia permission dialogs to work)"

    cd "$FRONTEND_DIR"

    # Check node_modules
    if [ ! -d "node_modules" ]; then
        log "Installing Node dependencies..."
        pnpm install
    fi

    # Check sidecar placeholder
    mkdir -p src-tauri/binaries
    ARCH=$(uname -m)
    if [ "$ARCH" = "arm64" ]; then
        SIDECAR="src-tauri/binaries/llama-helper-aarch64-apple-darwin"
    else
        SIDECAR="src-tauri/binaries/llama-helper-x86_64-apple-darwin"
    fi
    if [ ! -f "$SIDECAR" ]; then
        touch "$SIDECAR" && chmod +x "$SIDECAR"
        log "Created sidecar placeholder: $SIDECAR"
    fi

    # Build the Next.js frontend first
    log "Building Next.js frontend..."
    pnpm run build > "$FRONTEND_LOG" 2>&1
    success "Next.js build complete"

    # Build the Tauri app as a debug .app bundle
    # Note: The updater signing step may fail (no TAURI_SIGNING_PRIVATE_KEY) but
    # the .app bundle itself is created before that step, so we ignore the exit code
    log "Building Tauri .app bundle (debug mode)..."
    log "This takes ~1-3 min for incremental builds..."
    pnpm tauri build --debug --bundles app >> "$FRONTEND_LOG" 2>&1 || true
    
    if [ ! -d "$APP_BUNDLE" ]; then
        error "Failed to build .app bundle. Check: tail -50 $FRONTEND_LOG"
        return 1
    fi

    success "Built: $APP_BUNDLE"

    # Sign the .app bundle with entitlements
    ENTITLEMENTS="$FRONTEND_DIR/src-tauri/entitlements.plist"
    if [ -f "$ENTITLEMENTS" ]; then
        codesign --force --deep --sign - \
            --entitlements "$ENTITLEMENTS" \
            "$APP_BUNDLE" 2>/dev/null && \
            log "App bundle signed with entitlements"
    fi

    # Launch the .app bundle
    log "Launching Uchitil Live.app..."
    open "$APP_BUNDLE" &
    APP_PID=$!

    success "Uchitil Live.app launched!"
    success "macOS permission dialogs should now work correctly."
}

# Alternative: use tauri dev (faster iteration, but no permission dialogs on Sequoia)
start_frontend_dev() {
    log "Starting frontend in dev mode (tauri dev)..."
    warn "NOTE: Permission dialogs may NOT work in dev mode on macOS Sequoia."
    warn "Use './start.sh' (without 'dev') for proper .app bundle with permissions."

    cd "$FRONTEND_DIR"

    if [ ! -d "node_modules" ]; then
        log "Installing Node dependencies..."
        pnpm install
    fi

    mkdir -p src-tauri/binaries
    ARCH=$(uname -m)
    if [ "$ARCH" = "arm64" ]; then
        SIDECAR="src-tauri/binaries/llama-helper-aarch64-apple-darwin"
    else
        SIDECAR="src-tauri/binaries/llama-helper-x86_64-apple-darwin"
    fi
    if [ ! -f "$SIDECAR" ]; then
        touch "$SIDECAR" && chmod +x "$SIDECAR"
    fi

    pnpm run tauri:dev > "$FRONTEND_LOG" 2>&1 &
    FRONTEND_PID=$!

    log "Frontend building... (first run takes 3-5 min, subsequent runs ~30s)"
    log "Logs: tail -f $FRONTEND_LOG"

    for i in $(seq 1 300); do
        if grep -q "Compiled /" "$FRONTEND_LOG" 2>/dev/null; then
            success "Frontend dev server running!"
            return 0
        fi
        if grep -q "ELIFECYCLE\|panicked\|error\[" "$FRONTEND_LOG" 2>/dev/null; then
            error "Frontend build failed. Check: tail -50 $FRONTEND_LOG"
            return 1
        fi
        sleep 1
    done

    warn "Frontend is still building. Check: tail -f $FRONTEND_LOG"
}

MODE="${1:-all}"

echo ""
echo -e "${GREEN}  ╔══════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║        Uchitil Live v0.1.0        ║${NC}"
echo -e "${GREEN}  ║  Tutoring Session Recorder       ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════╝${NC}"
echo ""

case "$MODE" in
    backend)
        check_ollama
        start_backend
        log "Backend running. Press Ctrl+C to stop."
        wait "$BACKEND_PID"
        ;;
    frontend)
        start_frontend
        log "App launched. Press Ctrl+C to stop backend."
        wait
        ;;
    dev)
        check_ollama
        start_backend || exit 1
        start_frontend_dev
        echo ""
        success "================================================"
        success "  Uchitil Live DEV MODE"
        success "  Backend:  http://localhost:5167"
        success "  WARNING: Permission dialogs may not work!"
        success "  Use './start.sh' for proper .app bundle."
        success "================================================"
        wait
        ;;
    all)
        check_ollama
        start_backend || exit 1
        start_frontend
        echo ""
        success "================================================"
        success "  Uchitil Live is running!"
        success "  Backend:  http://localhost:5167"
        success "  API Docs: http://localhost:5167/docs"
        success "  Ollama:   http://localhost:11434"
        success "================================================"
        success "  Press Ctrl+C to stop all services"
        echo ""
        wait
        ;;
    stop)
        log "Stopping all Uchitil Live processes..."
        pkill -f "python app/main.py" 2>/dev/null && success "Backend stopped" || warn "No backend running"
        pkill -f "Uchitil Live" 2>/dev/null && success "App stopped" || warn "No app running"
        pkill -f "tauri" 2>/dev/null && success "Tauri stopped" || warn "No tauri running"
        ;;
    *)
        echo "Usage: ./start.sh [backend|frontend|all|dev|stop]"
        echo "  all       - Build .app bundle + start backend (default)"
        echo "  backend   - Start only the backend"
        echo "  frontend  - Build and launch .app bundle only"
        echo "  dev       - Dev mode (faster but no macOS permission dialogs)"
        echo "  stop      - Stop all running services"
        ;;
esac
