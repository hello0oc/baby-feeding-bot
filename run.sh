#!/usr/bin/env bash
set -e

echo "Starting Baby Feeding Bot..."

if [ ! -f .env ]; then
    echo "WARNING: .env file not found. Make sure environment variables are set:"
    echo "  - BABY_FEEDING_BOT_TOKEN"
    echo "  - GEMINI_API_KEY"
    echo ""
fi

if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "NOTE: No virtual environment found. Using system Python."
fi

if [ -f requirements.txt ]; then
    pip install -q -r requirements.txt
fi

python3 baby_feeding_bot.py