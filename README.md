# Baby Feeding Bot 🍼

A Telegram bot that analyzes food screenshots and suggests baby-friendly meal ideas for a 1-year-old child.

## Micro-MVP Features

- ✅ Receives photo messages via Telegram
- ✅ Uses Gemini vision API to analyze food images
- ✅ Generates 1-2 baby-friendly meal suggestions
- ✅ Responds directly in Telegram

## Quick Start

### 1. Install Dependencies

```bash
cd /home/deploy/.openclaw/workspace/projects/baby-feeding
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Set Environment Variables

```bash
export BABY_FEEDING_BOT_TOKEN="your_telegram_bot_token"
export GEMINI_API_KEY="your_gemini_api_key"
```

### 3. Run the Bot

```bash
./run.sh
```

Or manually:

```bash
source venv/bin/activate
python3 baby_feeding_bot.py
```

## Usage

1. Start a chat with your bot on Telegram
2. Send `/start` to see the welcome message
3. Send a photo of food (screenshot from social media, restaurant menu, etc.)
4. Receive 1-2 baby-friendly meal suggestions!

## Project Structure

```
baby-feeding/
├── baby_feeding_bot.py   # Main bot script
├── requirements.txt      # Python dependencies
├── run.sh               # Convenience run script
├── .env.example         # Environment variable template
└── README.md            # This file
```

## How It Works

1. **Photo Reception**: Bot receives photo via python-telegram-bot
2. **Image Processing**: Image is resized and converted to base64
3. **Vision Analysis**: Gemini vision API analyzes the food image
4. **Meal Generation**: AI generates age-appropriate meal suggestions
5. **Response**: Suggestions sent back to user in Telegram

## Running as a Service (Systemd)

To run the bot in the background and auto-start on boot:

```bash
# Copy service file
sudo cp baby-feeding-bot.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Start the bot
sudo systemctl start baby-feeding-bot

# Enable auto-start on boot
sudo systemctl enable baby-feeding-bot

# Check status
sudo systemctl status baby-feeding-bot

# View logs
sudo journalctl -u baby-feeding-bot -f
```

## Future Enhancements

- [ ] SQLite persistence for meal history
- [ ] Multiple user support with preferences
- [ ] Meal ratings and feedback
- [ ] Weekly meal plans
- [ ] Shopping list generation
- [ ] Integration as OpenClaw skill

## Notes

- Designed for babies around 1 year old
- Meal suggestions avoid: honey, choking hazards, excess salt/sugar
- Always consult with pediatrician for dietary advice
