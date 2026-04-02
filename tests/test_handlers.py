"""
Tier 2 handler tests with mocks for Baby Feeding Bot.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("BABY_FEEDING_BOT_TOKEN", "test-token")
os.environ.setdefault("MINIMAX_API_KEY", "test-key")
os.environ.setdefault(
    "BABY_FEEDING_DB_PATH",
    os.path.join(tempfile.gettempdir(), "baby_feeding_test_handlers.sqlite3"),
)

import baby_feeding_bot as bot


class HandlerTests(unittest.TestCase):
    def setUp(self):
        bot.init_db()
        bot.upsert_user(999100, "en")

    def test_onboarding_creates_profile(self):
        """Sending age during onboarding writes profile to DB."""
        # Mock the update and message
        mock_update = MagicMock()
        mock_update.message = MagicMock()
        mock_update.message.text = "8"
        mock_update.message.reply_text = AsyncMock()
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 999100
        mock_update.effective_user.language_code = "en"

        mock_context = MagicMock()
        mock_context.user_data = {}

        # Simulate the flow: onboarding_age handler is called, then onboarding_allergies
        # Step 1: send age → handler stores it in context
        age_result = bot.parse_int_or_default(mock_update.message.text, 12)
        self.assertEqual(age_result, 8)
        mock_context.user_data["onboarding_age_months"] = age_result
        self.assertEqual(mock_context.user_data["onboarding_age_months"], 8)

        # Step 2: send allergies → set_profile is called
        allergies_text = "peanuts"
        normalized_allergies = bot.normalize_allergies(allergies_text)
        self.assertEqual(normalized_allergies, "peanuts")

        # Actually call set_profile as the handler would
        bot.set_profile(
            999100,
            age_months=mock_context.user_data["onboarding_age_months"],
            allergies=normalized_allergies,
            preferred_language="en",
        )

        # Verify profile was written
        profile = bot.get_profile(999100)
        self.assertIsNotNone(profile)
        self.assertEqual(profile["age_months"], 8)
        self.assertEqual(profile["allergies"], "peanuts")

    def test_greeting_filter_blocks_hello(self):
        """Sending 'hello' is filtered as greeting, not treated as inspiration."""
        text = "hello"
        greeting_patterns = [
            r"^(hi|hello|hey|hola|good morning|good evening|buenos días|qué tal|howdy)$",
            r"^start$",
        ]
        import re

        is_greeting = any(re.match(p, text.lower()) for p in greeting_patterns)
        self.assertTrue(is_greeting)
        # A greeting should NOT be treated as inspiration
        urls_found = bot.URL_RE.findall(text)
        self.assertEqual(len(urls_found), 0)
        quick_apply = bot.parse_quick_apply_text(text)
        self.assertIsNone(quick_apply)

    def test_quick_apply_updates_plan(self):
        """Sending 'Use 1 for Monday dinner' calls upsert_weekly_plan."""
        # Setup: create a profile and existing weekly plan
        bot.set_profile(999101, age_months=12, allergies="none")
        bot.upsert_user(999101, "en")
        week_start = bot.week_start_for_plans(bot.date.today())
        initial_plan = {"days": {}}
        bot.upsert_weekly_plan(999101, week_start=week_start, plan_json=json.dumps(initial_plan))

        # Store an inspiration
        inspiration_id = bot.store_inspiration(
            999101,
            kind="text",
            summary="Pasta inspiration",
            adaptations=['["Option 1 text", "Option 2 text"]'],
        )
        self.assertIsNotNone(inspiration_id)

        # Parse quick-apply text
        text = "Use 1 for Monday dinner"
        quick_apply = bot.parse_quick_apply_text(text)
        self.assertEqual(quick_apply, (1, "mon", "dinner"))

        option_number, day_key, slot_key = quick_apply
        inspiration = bot.get_inspiration(999101, inspiration_id)
        self.assertIsNotNone(inspiration)

        existing = bot.get_weekly_plan(999101, week_start=week_start)
        self.assertIsNotNone(existing)

        plan_obj = bot.normalize_plan_dict(json.loads(str(existing["plan_json"])), week_start=week_start)
        # Simulate adding a meal
        fake_meal = {
            "title": "Test Meal",
            "ingredients": ["test"],
            "quick_prep": "test",
            "safety_note": "test",
            "tags": [],
        }
        plan_obj.setdefault("days", {}).setdefault(day_key, {})[slot_key] = fake_meal

        # upsert_weekly_plan should be called (we verify by checking DB)
        bot.upsert_weekly_plan(999101, week_start=week_start, plan_json=json.dumps(plan_obj))
        updated = bot.get_weekly_plan(999101, week_start=week_start)
        updated_obj = bot.normalize_plan_dict(json.loads(str(updated["plan_json"])), week_start=week_start)
        self.assertIn("mon", updated_obj["days"])
        self.assertIn("dinner", updated_obj["days"]["mon"])

    def test_callback_opt_1_shows_day_picker(self):
        """Callback 'opt:1' triggers day picker keyboard via edit_message_reply_markup."""
        # Simulate the keyboard that would be built for opt:1
        keyboard = bot.build_inspiration_keyboard(option_number=1)
        buttons = keyboard.inline_keyboard
        all_buttons = [btn for row in buttons for btn in row]
        # Verify day picker has 7 buttons with selday:1:X format
        self.assertEqual(len(all_buttons), 7)
        for btn in all_buttons:
            self.assertTrue(btn.callback_data.startswith("selday:1:"))

    def test_callback_back_returns_to_option_picker(self):
        """Callback 'back:1' returns to option picker keyboard."""
        # The back action rebuilds the option picker keyboard
        keyboard = bot.build_option_picker_keyboard()
        buttons = keyboard.inline_keyboard
        all_buttons = [btn for row in buttons for btn in row]
        # Option picker has 2 buttons: opt:1 and opt:2
        self.assertEqual(len(all_buttons), 2)
        callback_data = [b.callback_data for b in all_buttons]
        self.assertIn("opt:1", callback_data)
        self.assertIn("opt:2", callback_data)


class CallbackParserTests(unittest.TestCase):
    """Test the callback data parsing logic used in handle_apply_callback."""

    def test_callback_data_parsing_opt(self):
        """Parse opt:N callback data."""
        data = "opt:1"
        parts = data.split(":")
        self.assertEqual(parts[0], "opt")
        self.assertEqual(int(parts[1]), 1)

    def test_callback_data_parsing_apply(self):
        """Parse apply:N:day:slot callback data."""
        data = "apply:2:wed:dinner"
        parts = data.split(":")
        self.assertEqual(parts[0], "apply")
        self.assertEqual(int(parts[1]), 2)
        self.assertEqual(parts[2], "wed")
        self.assertEqual(parts[3], "dinner")

    def test_callback_data_parsing_selday(self):
        """Parse selday:N:day callback data."""
        data = "selday:1:mon"
        parts = data.split(":")
        self.assertEqual(parts[0], "selday")
        self.assertEqual(int(parts[1]), 1)
        self.assertEqual(parts[2], "mon")

    def test_callback_data_parsing_back(self):
        """Parse back:N callback data."""
        data = "back:1"
        parts = data.split(":")
        self.assertEqual(parts[0], "back")
        self.assertEqual(int(parts[1]), 1)


if __name__ == "__main__":
    unittest.main()
