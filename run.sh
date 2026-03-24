#!/bin/bash
# Run script for Baby Feeding Bot

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if virtual environment exists, create if not
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install/update dependencies
echo "Installing dependencies..."
pip install -q -r requirements.txt

# Check for required environment variables
if [ -z "$BABY_FEEDING_BOT_TOKEN" ]; then
    echo "Error: BABY_FEEDING_BOT_TOKEN environment variable not set"
    echo "Please set it with: export BABY_FEEDING_BOT_TOKEN='your_token_here'"
    exit 1
fi

if [ -z "$GEMINI_API_KEY" ]; then
    echo "Error: GEMINI_API_KEY environment variable not set"
    echo "Please set it with: export GEMINI_API_KEY='your_key_here'"
    exit 1
fi

# Run the bot
echo "Starting Baby Feeding Bot..."
python3 baby_feeding_bot.py
