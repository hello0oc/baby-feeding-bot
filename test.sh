#!/usr/bin/env bash
set -e

echo "=== Baby Feeding Bot - Environment Verification ==="

echo "Checking Python..."
python3 --version

echo "Checking pip dependencies..."
pip install -q -r requirements.txt 2>/dev/null || true

echo "Checking environment variables..."
if [ -z "$BABY_FEEDING_BOT_TOKEN" ]; then
    echo "WARNING: BABY_FEEDING_BOT_TOKEN not set"
else
    echo "OK: BABY_FEEDING_BOT_TOKEN is set"
fi

if [ -z "$GEMINI_API_KEY" ]; then
    echo "WARNING: GEMINI_API_KEY not set"
else
    echo "OK: GEMINI_API_KEY is set"
fi

echo ""
echo "=== Running unit and integration tests ==="
python3 -m pytest tests/ -v --tb=short 2>/dev/null || python3 -m unittest discover -s tests -v

echo ""
echo "=== Environment check complete ==="
echo "To start the bot:"
echo "  source venv/bin/activate && python3 baby_feeding_bot.py"