#!/usr/bin/env bash
# =============================================================================
# Baby Feeding Bot — Restart Script
# Safely stops the running bot, then starts it fresh with logging.
#
# Usage:
#   ./scripts/restart_bot.sh
#
# Requirements:
#   - .env file in the project root (or exported env vars)
#   - Python virtualenv at ./venv/
#   - Logging directory at ./logs/
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
PID_FILE="$PROJECT_DIR/bot.pid"
BOT_SCRIPT="$PROJECT_DIR/baby_feeding_bot.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

# =============================================================================
# Pre-flight checks
# =============================================================================

cd "$PROJECT_DIR"

if [[ ! -f "$BOT_SCRIPT" ]]; then
    log_error "Bot script not found at: $BOT_SCRIPT"
    exit 1
fi

if [[ ! -d "$PROJECT_DIR/venv" ]]; then
    log_error "Virtualenv not found at: $PROJECT_DIR/venv"
    log_error "Run: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
    exit 1
fi

if [[ ! -f "$PROJECT_DIR/.env" ]]; then
    log_warn ".env file not found — relying on exported environment variables"
else
    log_info "Loading environment from .env"
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# Create log directory
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/bot.log"

# =============================================================================
# Stop existing bot process
# =============================================================================

stop_bot() {
    if [[ -f "$PID_FILE" ]]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            log_info "Stopping bot (PID $PID) gracefully..."
            kill -TERM "$PID"
            # Wait up to 10s for graceful shutdown
            for i in $(seq 1 10); do
                if ! kill -0 "$PID" 2>/dev/null; then
                    log_info "Bot stopped gracefully."
                    return 0
                fi
                sleep 1
            done
            log_warn "Bot did not stop gracefully, forcing..."
            kill -9 "$PID" 2>/dev/null || true
        else
            log_warn "PID file exists but process $PID is not running."
        fi
        rm -f "$PID_FILE"
    else
        # Try to find by process name
        EXISTING_PID=$(pgrep -f "baby_feeding_bot.py" 2>/dev/null || true)
        if [[ -n "$EXISTING_PID" ]]; then
            log_info "Found running bot (PID $EXISTING_PID), stopping..."
            kill -TERM "$EXISTING_PID" 2>/dev/null || true
            sleep 2
        else
            log_info "No running bot found."
        fi
    fi
}

stop_bot

# =============================================================================
# Start bot
# =============================================================================

log_info "Starting bot..."
log_info "Logging to: $LOG_FILE"

# Activate venv and start bot with nohup
cd "$PROJECT_DIR"
nohup "$PROJECT_DIR/venv/bin/python" "$BOT_SCRIPT" >> "$LOG_FILE" 2>&1 &
BOT_PID=$!

echo "$BOT_PID" > "$PID_FILE"

log_info "Bot started with PID $BOT_PID"

# =============================================================================
# Verify startup
# =============================================================================

sleep 3

if kill -0 "$BOT_PID" 2>/dev/null; then
    log_info "Bot is running (PID $BOT_PID)"
    echo ""
    echo "  PID file:   $PID_FILE"
    echo "  Log file:   $LOG_FILE"
    echo "  View logs:  tail -f $LOG_FILE"
    echo "  Stop bot:   kill \$(cat $PID_FILE)"
    echo ""
else
    log_error "Bot failed to start. Check $LOG_FILE for errors."
    echo ""
    echo "Last 20 lines of log:"
    tail -20 "$LOG_FILE"
    echo ""
    rm -f "$PID_FILE"
    exit 1
fi
