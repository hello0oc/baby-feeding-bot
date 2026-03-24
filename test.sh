#!/bin/bash
# Test script to verify bot setup

cd /home/deploy/.openclaw/workspace/projects/baby-feeding
source venv/bin/activate

echo "Testing Baby Feeding Bot setup..."
echo

# Test Python imports
echo "Testing imports..."
python3 -c "
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import httpx
from dotenv import load_dotenv
from PIL import Image
print('✓ All Python imports successful')
"

# Check environment
echo
echo "Environment check:"
if [ -z "$BABY_FEEDING_BOT_TOKEN" ]; then
    echo "⚠ BABY_FEEDING_BOT_TOKEN not set (will use default in run.sh)"
else
    echo "✓ BABY_FEEDING_BOT_TOKEN is set"
fi

if [ -z "$GEMINI_API_KEY" ]; then
    echo "✗ GEMINI_API_KEY not set (required for image analysis)"
else
    echo "✓ GEMINI_API_KEY is set"
fi

echo
echo "Setup test complete!"
echo "Run './run.sh' to start the bot."
