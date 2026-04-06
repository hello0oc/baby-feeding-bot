"""Tests for the new usability improvements."""
import os
import tempfile
import unittest

os.environ.setdefault("BABY_FEEDING_BOT_TOKEN", "test-token")
os.environ.setdefault("MINIMAX_API_KEY", "test-key")
os.environ.setdefault(
    "BABY_FEEDING_DB_PATH",
    os.path.join(tempfile.gettempdir(), "baby_feeding_test_new_features.sqlite3"),
)

import baby_feeding_bot as bot


class SeverityIndicatorTests(unittest.TestCase):
    def test_severity_indicator_tolerated(self):
        self.assertEqual(bot.severity_indicator("mild", "tolerated"), "✅")
        self.assertEqual(bot.severity_indicator("moderate", "tolerated"), "✅")
        self.assertEqual(bot.severity_indicator("severe", "tolerated"), "✅")

    def test_severity_indicator_reaction(self):
        self.assertEqual(bot.severity_indicator("mild", "reaction"), "🚨")
        self.assertEqual(bot.severity_indicator("moderate", "reaction"), "🚨")
        self.assertEqual(bot.severity_indicator("severe", "reaction"), "🚨")

    def test_severity_indicator_moderate(self):
        self.assertEqual(bot.severity_indicator("moderate", None), "⚠️ moderate")
        self.assertEqual(bot.severity_indicator("moderate", "unknown"), "⚠️ moderate")

    def test_severity_indicator_mild(self):
        self.assertEqual(bot.severity_indicator("mild", None), "⚠️ mild")
        self.assertEqual(bot.severity_indicator("mild", "unknown"), "⚠️ mild")

    def test_severity_indicator_severe_no_outcome(self):
        self.assertEqual(bot.severity_indicator("severe", None), "🚨")

    def test_severity_indicator_unknown(self):
        self.assertEqual(bot.severity_indicator(None, None), "❓")
        self.assertEqual(bot.severity_indicator("unknown", None), "❓")

    def test_severity_indicator_spanish(self):
        self.assertEqual(bot.severity_indicator("moderate", None, "es"), "⚠️ moderate")
        self.assertEqual(bot.severity_indicator("mild", None, "es"), "⚠️ mild")


class AllergenJournalKeyboardTests(unittest.TestCase):
    def test_build_allergen_journal_keyboard_has_new_button(self):
        kb = bot.build_allergen_journal_keyboard()
        buttons = [b.text for row in kb.inline_keyboard for b in row]
        self.assertIn("🥜 Log new allergen", buttons)

    def test_build_allergen_journal_keyboard_has_quick_add(self):
        kb = bot.build_allergen_journal_keyboard()
        buttons = [b.text for row in kb.inline_keyboard for b in row]
        self.assertIn("🥛 Milk", buttons)
        self.assertIn("🥚 Egg", buttons)
        self.assertIn("🥜 Peanut", buttons)

    def test_build_allergen_journal_keyboard_quick_callback(self):
        kb = bot.build_allergen_journal_keyboard()
        callback_map = {b.text: b.callback_data for row in kb.inline_keyboard for b in row}
        self.assertEqual(callback_map.get("🥛 Milk"), "aj_quick:milk")
        self.assertEqual(callback_map.get("🥚 Egg"), "aj_quick:egg")
        self.assertEqual(callback_map.get("🥜 Peanut"), "aj_quick:peanut")

    def test_build_severity_keyboard_has_all_options(self):
        kb = bot.build_severity_keyboard()
        buttons = [b.text for row in kb.inline_keyboard for b in row]
        self.assertIn("✅ Tolerated", buttons)
        self.assertIn("⚠️ Mild", buttons)
        self.assertIn("⚠️ Moderate", buttons)
        self.assertIn("🚨 Severe", buttons)
        self.assertIn("❓ Unknown", buttons)

    def test_build_severity_keyboard_callbacks(self):
        kb = bot.build_severity_keyboard()
        callback_map = {b.text: b.callback_data for row in kb.inline_keyboard for b in row}
        self.assertEqual(callback_map["✅ Tolerated"], "intro_outcome:tolerated")
        self.assertEqual(callback_map["⚠️ Mild"], "intro_severity:mild")
        self.assertEqual(callback_map["⚠️ Moderate"], "intro_severity:moderate")
        self.assertEqual(callback_map["🚨 Severe"], "intro_severity:severe")
        self.assertEqual(callback_map["❓ Unknown"], "intro_severity:unknown")


class NutritionSummaryTests(unittest.TestCase):
    def test_nutrition_summary_header_english(self):
        plan = {"days": {"mon": {"breakfast": {"title": "Cereal", "ingredients": [], "tags": ["iron-rich"]}}}}
        summary = bot.generate_nutrition_summary(plan, 14, "en")
        self.assertIn("📊 Nutrition Summary", summary)

    def test_nutrition_summary_header_chinese(self):
        plan = {"days": {}}
        summary = bot.generate_nutrition_summary(plan, 14, "zh")
        self.assertIn("📊 营养摘要", summary)

    def test_nutrition_summary_under_12mo(self):
        plan = {"days": {}}
        summary = bot.generate_nutrition_summary(plan, 8, "en")
        self.assertIn("Under 12 months", summary)

    def test_nutrition_summary_iron_good_coverage(self):
        plan = {
            "days": {
                "mon": {"breakfast": {"title": "Cereal", "ingredients": [], "tags": ["iron-rich"]}},
                "tue": {"lunch": {"title": "Meat", "ingredients": [], "tags": ["iron"]}},
                "wed": {"dinner": {"title": "Lentils", "ingredients": [], "tags": ["iron-rich"]}},
                "thu": {"snack1": {"title": "Spinach", "ingredients": [], "tags": ["iron"]}},
            }
        }
        summary = bot.generate_nutrition_summary(plan, 14, "en")
        self.assertIn("Iron:", summary)
        self.assertIn("Good coverage", summary)

    def test_nutrition_summary_iron_low(self):
        # Build a plan with iron only on a few days (below the 4-day threshold for "good coverage")
        plan = {
            "days": {
                "mon": {"breakfast": {"title": "Cereal", "ingredients": [], "tags": ["iron-rich"]}},
                "tue": {"lunch": {"title": "Toast", "ingredients": [], "tags": []}},
                "wed": {"dinner": {"title": "Rice", "ingredients": [], "tags": []}},
                "thu": {"snack1": {"title": "Apple", "ingredients": [], "tags": []}},
                "fri": {"breakfast": {"title": "Oats", "ingredients": [], "tags": []}},
                "sat": {"lunch": {"title": "Pasta", "ingredients": [], "tags": []}},
                "sun": {"dinner": {"title": "Soup", "ingredients": [], "tags": []}},
            }
        }
        summary = bot.generate_nutrition_summary(plan, 14, "en")
        self.assertIn("Iron:", summary)
        # Only 1 day has iron-rich tag, below threshold for "good coverage"
        # Should NOT say "No iron-rich" (which means 0 days)
        self.assertIn("Mon", summary)

    def test_nutrition_summary_calcium_low(self):
        plan = {"days": {"mon": {"breakfast": {"title": "Toast", "ingredients": [], "tags": []}}}}
        summary = bot.generate_nutrition_summary(plan, 14, "en")
        self.assertIn("Calcium:", summary)
        self.assertIn("No calcium-rich meals", summary)

    def test_nutrition_summary_calcium_good(self):
        plan = {
            "days": {
                "mon": {"breakfast": {"title": "Yogurt", "ingredients": [], "tags": ["calcium-rich"]}},
                "tue": {"lunch": {"title": "Cheese", "ingredients": [], "tags": ["calcium"]}},
                "wed": {"dinner": {"title": "Milk", "ingredients": [], "tags": ["calcium-rich"]}},
                "thu": {"snack1": {"title": "Cottage cheese", "ingredients": [], "tags": ["calcium"]}},
                "fri": {"lunch": {"title": "Paneer", "ingredients": [], "tags": ["calcium"]}},
            }
        }
        summary = bot.generate_nutrition_summary(plan, 14, "en")
        self.assertIn("Calcium:", summary)
        self.assertIn("Good coverage", summary)

    def test_nutrition_summary_vitc_helps_iron(self):
        plan = {
            "days": {
                "mon": {"breakfast": {"title": "Cereal", "ingredients": [], "tags": ["iron-rich"]}},
                "tue": {"snack1": {"title": "Orange", "ingredients": [], "tags": ["vitamin c"]}},
            }
        }
        summary = bot.generate_nutrition_summary(plan, 14, "en")
        self.assertIn("Vitamin C:", summary)
        self.assertIn("pairs well", summary)


class WeeklyPlanKeyboardTests(unittest.TestCase):
    def test_build_weekly_plan_keyboard_has_nutrition_button(self):
        kb = bot.build_weekly_plan_keyboard()
        buttons = [b.text for row in kb.inline_keyboard for b in row]
        self.assertIn("📊 Nutrition", buttons)

    def test_build_weekly_plan_keyboard_has_lang_toggle(self):
        kb = bot.build_weekly_plan_keyboard()
        buttons = [b.text for row in kb.inline_keyboard for b in row]
        # Two language options: EN and ZH
        self.assertIn("🌐 EN", buttons)
        self.assertIn("ZH", buttons)

    def test_build_weekly_plan_keyboard_nutrition_callback(self):
        kb = bot.build_weekly_plan_keyboard()
        callback_map = {b.text: b.callback_data for row in kb.inline_keyboard for b in row}
        self.assertEqual(callback_map["📊 Nutrition"], "nutrition")

    def test_build_weekly_plan_keyboard_lang_callback(self):
        kb = bot.build_weekly_plan_keyboard()
        callback_map = {b.text: b.callback_data for row in kb.inline_keyboard for b in row}
        self.assertEqual(callback_map["🌐 EN"], "lang:en")
        self.assertEqual(callback_map["ZH"], "lang:zh")


class UpdateAllergenIntroTests(unittest.TestCase):
    def test_update_allergen_intro_adds_severity(self):
        # Use a unique user ID to avoid conflicts
        bot.init_db()
        uid = 999991
        bot.introduce_allergen(uid, "peanut")
        bot.update_allergen_intro(uid, "peanut", severity="mild", outcome="tolerated")
        entries = bot.get_allergen_journal(uid)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["severity"], "mild")
        self.assertEqual(entries[0]["outcome"], "tolerated")

    def test_update_allergen_intro_updates_existing(self):
        bot.init_db()
        uid = 999992
        bot.introduce_allergen(uid, "egg", severity="unknown", outcome="unknown")
        bot.update_allergen_intro(uid, "egg", severity="moderate", outcome="reaction")
        entries = bot.get_allergen_journal(uid)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["severity"], "moderate")
        self.assertEqual(entries[0]["outcome"], "reaction")


class DayDetailKeyboardTests(unittest.TestCase):
    def test_build_day_detail_keyboard_has_back_button(self):
        kb = bot.build_day_detail_keyboard("mon")
        buttons = [b.text for row in kb.inline_keyboard for b in row]
        self.assertIn("« Back to week", buttons)


if __name__ == "__main__":
    unittest.main()
