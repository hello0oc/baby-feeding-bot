"""
Tests for inline keyboard builder functions.
"""
import os
import tempfile
import unittest

os.environ.setdefault("BABY_FEEDING_BOT_TOKEN", "test-token")
os.environ.setdefault("MINIMAX_API_KEY", "test-key")
os.environ.setdefault(
    "BABY_FEEDING_DB_PATH",
    os.path.join(tempfile.gettempdir(), "baby_feeding_test_keyboards.sqlite3"),
)

import baby_feeding_bot as bot


class KeyboardBuilderTests(unittest.TestCase):
    def test_build_option_picker_keyboard(self):
        """Option picker keyboard has 2 buttons with correct callback data."""
        keyboard = bot.build_option_picker_keyboard()
        self.assertIsNotNone(keyboard)
        self.assertIsInstance(keyboard, bot.InlineKeyboardMarkup)
        buttons = keyboard.inline_keyboard
        self.assertEqual(len(buttons), 2)
        # Check first button
        self.assertEqual(len(buttons[0]), 1)
        self.assertEqual(buttons[0][0].callback_data, "opt:1")
        # Check second button
        self.assertEqual(len(buttons[1]), 1)
        self.assertEqual(buttons[1][0].callback_data, "opt:2")

    def test_build_inspiration_keyboard_option1(self):
        """Option 1 keyboard has 7 day buttons with selday:1:X format."""
        keyboard = bot.build_inspiration_keyboard(option_number=1)
        self.assertIsNotNone(keyboard)
        buttons = keyboard.inline_keyboard
        # Collect all buttons
        all_buttons = [btn for row in buttons for btn in row]
        self.assertEqual(len(all_buttons), 7)
        expected_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        for btn in all_buttons:
            self.assertTrue(btn.callback_data.startswith("selday:1:"))
            day = btn.callback_data.split(":")[-1]
            self.assertIn(day, expected_days)

    def test_build_inspiration_keyboard_option2(self):
        """Option 2 keyboard has 7 day buttons with selday:2:X format."""
        keyboard = bot.build_inspiration_keyboard(option_number=2)
        self.assertIsNotNone(keyboard)
        buttons = keyboard.inline_keyboard
        all_buttons = [btn for row in buttons for btn in row]
        self.assertEqual(len(all_buttons), 7)
        expected_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        for btn in all_buttons:
            self.assertTrue(btn.callback_data.startswith("selday:2:"))
            day = btn.callback_data.split(":")[-1]
            self.assertIn(day, expected_days)

    def test_build_slot_keyboard(self):
        """Slot keyboard has 5 slot buttons + back, with apply:N:day:slot format."""
        keyboard = bot.build_slot_keyboard(option_number=1, day_key="mon")
        self.assertIsNotNone(keyboard)
        buttons = keyboard.inline_keyboard
        # Should have 5 slot buttons + 1 back button = 6 rows (some slots grouped)
        slot_buttons = [btn for row in buttons for btn in row]
        # Check back button
        back_btn = slot_buttons[-1]
        self.assertEqual(back_btn.callback_data, "back:1")
        # Check slot buttons have correct apply format
        expected_slots = {"breakfast", "snack1", "lunch", "snack2", "dinner"}
        for btn in slot_buttons[:-1]:
            self.assertTrue(btn.callback_data.startswith("apply:1:mon:"))
            slot = btn.callback_data.split(":")[-1]
            self.assertIn(slot, expected_slots)

    def test_back_button_callback_data(self):
        """Back button format is back:N."""
        keyboard = bot.build_slot_keyboard(option_number=3, day_key="wed")
        buttons = keyboard.inline_keyboard
        all_buttons = [btn for row in buttons for btn in row]
        back_buttons = [b for b in all_buttons if b.callback_data.startswith("back:")]
        self.assertEqual(len(back_buttons), 1)
        self.assertEqual(back_buttons[0].callback_data, "back:3")


if __name__ == "__main__":
    unittest.main()
