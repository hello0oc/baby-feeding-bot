# Baby Feeding Bot

A Telegram bot that helps parents turn food inspirations into baby-friendly meals and build weekly meal plans for toddlers (12+ months).

## Features

- **Multi-format inspiration**: Send food photos, links, or text ideas
- **Smart adaptations**: AI generates 2 baby-safe options from any inspiration
- **Weekly planning**: Build a complete weekly meal plan with 5 slots per day
- **Flexible swapping**: Use "Use 1 for Wednesday dinner" to swap any meal
- **Shopping lists**: Auto-generated from your weekly plan
- **Bilingual**: Full English and Spanish support
- **Profile-aware**: Respects your baby's age and allergies

## Quick Start

### 1. Install Dependencies

```bash
cd baby-feeding-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Set Environment Variables

Create a `.env` file or export:

```bash
export BABY_FEEDING_BOT_TOKEN="your_telegram_bot_token"
export GEMINI_API_KEY="your_gemini_api_key"
```

### 3. Run the Bot

```bash
source venv/bin/activate
python3 baby_feeding_bot.py
```

Or use the convenience script:

```bash
./run.sh
```

## Usage

### First Run (Onboarding)

1. Start a chat with your bot on Telegram
2. Send `/start`
3. Enter your baby's age in months
4. List any allergies or foods to avoid
5. You're ready to go!

### Sending Inspirations

**Photo**: Send any food photo and the bot will suggest 2 baby-friendly adaptations.

**Text**: Type a meal idea like "pasta with broccoli" and get suggestions.

**Link**: Paste a link to a recipe and the bot will extract the theme.

### Weekly Plan

Tap **📅 Weekly plan** to generate a personalized weekly meal plan based on your recent inspirations.

The plan covers:
- Breakfast, morning snack, lunch, afternoon snack, dinner
- For each day: Monday through Sunday

### Swapping Meals

After receiving meal suggestions, reply with:

```
Use 1 for Wednesday dinner
```

This swaps the suggested Option 1 into your weekly plan at that slot.

### Shopping List

Tap **🛒 Shopping list** after generating a weekly plan to get a consolidated shopping list grouped by category.

### Profile Updates

- **👶 Update age**: Change your baby's age
- **🥜 Update allergies**: Update allergy information

## Command Reference

| Command | Description |
|---------|-------------|
| `/start` | Start or return to the bot |
| `/weekly_plan` | Generate or view your weekly plan |
| `/shopping_list` | Get a shopping list from your plan |
| `/history` | View recent plans and inspirations |
| `/set_age <months>` | Set baby age (e.g., `/set_age 14`) |
| `/set_allergies <list>` | Set allergies (e.g., `/set_allergies peanuts, milk`) |
| `/apply <id> <day> <slot>` | Apply inspiration to a slot |
| `/rate <meal_id> <up\|down\|0> [comment]` | Rate a meal |
| `/help` | Show help |

## Project Structure

```
baby-feeding-bot/
├── baby_feeding_bot.py   # Main bot script
├── requirements.txt      # Python dependencies
├── run.sh               # Convenience run script
├── test.sh              # Environment verification
├── .env.example         # Environment variable template
├── README.md            # This file
└── tests/
    ├── test_helpers.py      # Unit tests for parsing/rendering
    └── test_bot_flows.py    # Integration tests
```

## How It Works

1. **Inspiration Reception**: Bot receives photos via python-telegram-bot, extracts URLs, or accepts text input
2. **AI Analysis**: Gemini vision API analyzes food images; text/links are processed directly
3. **Adaptation Generation**: AI generates 2 baby-safe meal adaptations respecting age and allergy constraints
4. **Weekly Planning**: AI builds a full weekly plan with 5 slots per day, 7 days per week
5. **Shopping List**: AI consolidates all ingredients into a categorized shopping list
6. **Persistence**: SQLite stores users, profiles, inspirations, plans, and feedback

## Testing

```bash
./test.sh
```

Or directly:

```bash
python3 -m pytest tests/ -v
```

Tests cover:
- Parsing and normalization helpers
- JSON extraction and meal plan normalization
- Rendering functions (meal cards, weekly plans, shopping lists)
- Onboarding flows
- Quick-apply and swap flows
- Failure cases (missing profile, invalid slot/day, etc.)

## Running as a Service (Systemd)

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
journalctl -u baby-feeding-bot -f
```

## Deployment Notes

- Bot requires Python 3.9+
- Database is SQLite (file path configurable via `BABY_FEEDING_DB_PATH`)
- Image analysis requires significant memory; images are resized to max 1024px before processing
- Data retention: inspirations kept 90 days, feedback 90 days, plans 365 days (all configurable)

## Safety Guidelines

- Meals are designed for babies 12+ months
- Always check with your pediatrician for dietary advice
- The bot avoids: honey, choking hazards, excess salt, added sugar, raw/undercooked foods
- Supervision is always recommended during feeding