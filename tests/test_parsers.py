"""
Tests for parser functions (normalize_day, normalize_slot, parse_quick_apply_text, normalize_allergies).
"""
import os
import tempfile
import unittest

os.environ.setdefault("BABY_FEEDING_BOT_TOKEN", "test-token")
os.environ.setdefault("MINIMAX_API_KEY", "test-key")
os.environ.setdefault(
    "BABY_FEEDING_DB_PATH",
    os.path.join(tempfile.gettempdir(), "baby_feeding_test_parsers.sqlite3"),
)

import baby_feeding_bot as bot


class NormalizeDayTests(unittest.TestCase):
    def test_normalize_day_all_variants(self):
        """All day name variants normalize to expected short form."""
        cases = [
            ("mon", "mon"),
            ("Mon", "mon"),
            ("MON", "mon"),
            ("monday", "mon"),
            ("Monday", "mon"),
            ("MONDAY", "mon"),
            ("tue", "tue"),
            ("Tuesday", "tue"),
            ("wed", "wed"),
            ("Wednesday", "wed"),
            ("thu", "thu"),
            ("Thursday", "thu"),
            ("fri", "fri"),
            ("Friday", "fri"),
            ("sat", "sat"),
            ("Saturday", "sat"),
            ("sun", "sun"),
            ("Sunday", "sun"),
            ("invalid", None),
            ("", None),
            ("mond", None),
            ("january", None),
        ]
        for input_val, expected in cases:
            result = bot.normalize_day(input_val)
            self.assertEqual(result, expected, f"Failed for: {input_val!r}")


class NormalizeSlotTests(unittest.TestCase):
    def test_normalize_slot(self):
        """All slot variants normalize correctly."""
        cases = [
            ("breakfast", "breakfast"),
            ("Breakfast", "breakfast"),
            ("BREAKFAST", "breakfast"),
            ("snack1", "snack1"),
            ("snack 1", "snack1"),
            ("morning snack", "snack1"),
            ("Morning Snack", "snack1"),
            ("snack2", "snack2"),
            ("snack 2", "snack2"),
            ("afternoon snack", "snack2"),
            ("Afternoon Snack", "snack2"),
            ("lunch", "lunch"),
            ("Lunch", "lunch"),
            ("dinner", "dinner"),
            ("Dinner", "dinner"),
            ("invalid", None),
            ("", None),
            ("supper", None),
        ]
        for input_val, expected in cases:
            result = bot.normalize_slot(input_val)
            self.assertEqual(result, expected, f"Failed for: {input_val!r}")


class ParseQuickApplyTests(unittest.TestCase):
    def test_parse_quick_apply_valid(self):
        """Valid quick-apply strings parse to (option, day, slot)."""
        result = bot.parse_quick_apply_text("Use 1 for Wednesday dinner")
        self.assertEqual(result, (1, "wed", "dinner"))

    def test_parse_quick_apply_case_insensitive(self):
        """Quick-apply parsing is case-insensitive."""
        result = bot.parse_quick_apply_text("use 2 for MON LUNCH")
        self.assertEqual(result, (2, "mon", "lunch"))
        result2 = bot.parse_quick_apply_text("APPLY 1 FOR FRIDAY BREAKFAST")
        self.assertEqual(result2, (1, "fri", "breakfast"))
        result3 = bot.parse_quick_apply_text("Use 1 for TUE snack1")
        self.assertEqual(result3, (1, "tue", "snack1"))

    def test_parse_quick_apply_invalid(self):
        """Invalid inputs return None."""
        invalid_cases = [
            "hello",
            "Use 3 for Monday dinner",
            "",
            "Use 1",
            "Monday dinner",
            "Use 1 for Tuesday",
            "apply 1 for mon",
        ]
        for text in invalid_cases:
            result = bot.parse_quick_apply_text(text)
            self.assertIsNone(result, f"Should be None for: {text!r}")


class NormalizeAllergiesTests(unittest.TestCase):
    def test_normalize_allergies(self):
        """Allergy normalization works correctly."""
        cases = [
            ("none", "none"),
            ("None", "none"),
            ("NONE", "none"),
            ("no", "none"),
            ("n/a", "none"),
            ("N/A", "none"),
            ("Peanut, egg", "Peanut, egg"),
            ("peanuts, milk", "peanuts, milk"),
            ("Peanuts\nMilk", "Peanuts, Milk"),
            ("milk; eggs", "milk, eggs"),
            ("", "none"),
            ("  ", "none"),
            ("  none  ", "none"),
        ]
        for input_val, expected in cases:
            result = bot.normalize_allergies(input_val)
            self.assertEqual(result, expected, f"Failed for: {input_val!r}")


if __name__ == "__main__":
    unittest.main()
