"""
Tests for renderer functions (render_adaptation_card, render_weekly_plan).
"""
import os
import tempfile
import unittest

os.environ.setdefault("BABY_FEEDING_BOT_TOKEN", "test-token")
os.environ.setdefault("MINIMAX_API_KEY", "test-key")
os.environ.setdefault(
    "BABY_FEEDING_DB_PATH",
    os.path.join(tempfile.gettempdir(), "baby_feeding_test_renderers.sqlite3"),
)

import baby_feeding_bot as bot


class RenderAdaptationCardTests(unittest.TestCase):
    def test_render_adaptation_card_normal(self):
        """Normal text renders with title + body, no error signals."""
        adaptation = "Banana Oatmeal\nMash banana with oats\nAdd water\nServe soft"
        result = bot.render_adaptation_card(1, adaptation)
        self.assertIn("Option 1", result)
        self.assertIn("Banana Oatmeal", result)
        self.assertIn("Mash banana", result)
        # Should not contain error signals
        self.assertNotIn("sorry", result.lower())
        self.assertNotIn("trouble", result.lower())

    def test_render_adaptation_card_empty(self):
        """Empty string shows 'Generating...' not a fake success."""
        result = bot.render_adaptation_card(1, "")
        self.assertIn("Generating...", result)
        self.assertIn("Option 1", result)  # Option label is present even when empty

    def test_render_adaptation_card_error(self):
        """Error text is shown verbatim in the card."""
        error_text = "Sorry, I had trouble generating this option"
        result = bot.render_adaptation_card(1, error_text)
        self.assertIn("Sorry, I had trouble", result)


class RenderWeeklyPlanTests(unittest.TestCase):
    def test_render_weekly_plan_empty(self):
        """Empty days shows 'No meals planned yet.'."""
        result = bot.render_weekly_plan({"days": {}})
        self.assertIn("No meals planned", result)

    def test_render_weekly_plan_partial(self):
        """Only Monday breakfast shows Monday section only."""
        plan = {
            "days": {
                "mon": {
                    "breakfast": {
                        "title": "Oatmeal",
                        "ingredients": ["oats", "banana"],
                        "quick_prep": "Mix",
                        "safety_note": "Soft",
                        "tags": [],
                    }
                }
            }
        }
        result = bot.render_weekly_plan(plan)
        self.assertIn("Monday", result)
        self.assertIn("Oatmeal", result)
        self.assertNotIn("Tuesday", result)
        self.assertNotIn("Wednesday", result)

    def test_render_weekly_plan_full(self):
        """All 35 slots renders without crash."""
        days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        slots = ["breakfast", "snack1", "lunch", "snack2", "dinner"]
        plan_days = {}
        for day in days:
            plan_days[day] = {}
            for slot in slots:
                plan_days[day][slot] = {
                    "title": f"Meal for {day} {slot}",
                    "ingredients": ["ingredient1", "ingredient2"],
                    "quick_prep": "Quick prep",
                    "safety_note": "Safe",
                    "tags": ["protein"],
                }
        plan = {"days": plan_days}
        # Should not raise
        result = bot.render_weekly_plan(plan)
        # Should contain content
        self.assertIn("Monday", result)
        self.assertIn("Sunday", result)
        self.assertIn("Meal for mon breakfast", result)
        self.assertIn("Meal for sun dinner", result)


if __name__ == "__main__":
    unittest.main()
