import json
import os
import tempfile
import unittest

os.environ.setdefault("BABY_FEEDING_BOT_TOKEN", "test-token")
os.environ.setdefault("MINIMAX_API_KEY", "test-key")
os.environ.setdefault(
    "BABY_FEEDING_DB_PATH",
    os.path.join(tempfile.gettempdir(), "baby_feeding_test_bot_flows.sqlite3"),
)

import baby_feeding_bot as bot


class QuickApplyParsingTests(unittest.TestCase):
    def test_parse_quick_apply_text_recognized(self):
        cases = [
            ("Use 1 for Wednesday dinner", (1, "wed", "dinner")),
            ("apply 2 to mon snack 1", (2, "mon", "snack1")),
            ("Use 2 for Friday lunch", (2, "fri", "lunch")),
            ("Apply 1 for Monday breakfast", (1, "mon", "breakfast")),
        ]
        for text, expected in cases:
            result = bot.parse_quick_apply_text(text)
            self.assertEqual(result, expected, f"Failed for: {text}")

    def test_parse_quick_apply_text_invalid(self):
        invalid_cases = [
            "Invalid text",
            "Use 3 for Monday dinner",
            "Use 1",
            "Wednesday dinner",
        ]
        for text in invalid_cases:
            result = bot.parse_quick_apply_text(text)
            self.assertIsNone(result, f"Should be None for: {text}")


class NormalizationTests(unittest.TestCase):
    def test_normalize_day_all_variants(self):
        cases = [
            ("monday", "mon"),
            ("mon", "mon"),
            ("tuesday", "tue"),
            ("tue", "tue"),
            ("wednesday", "wed"),
            ("thursday", "thu"),
            ("friday", "fri"),
            ("saturday", "sat"),
            ("sunday", "sun"),
            ("invalid", None),
            ("", None),
        ]
        for input_val, expected in cases:
            result = bot.normalize_day(input_val)
            self.assertEqual(result, expected, f"Failed for: {input_val}")

    def test_normalize_slot_all_variants(self):
        cases = [
            ("breakfast", "breakfast"),
            ("snack1", "snack1"),
            ("snack 1", "snack1"),
            ("morning snack", "snack1"),
            ("snack2", "snack2"),
            ("afternoon snack", "snack2"),
            ("lunch", "lunch"),
            ("dinner", "dinner"),
            ("invalid", None),
        ]
        for input_val, expected in cases:
            result = bot.normalize_slot(input_val)
            self.assertEqual(result, expected, f"Failed for: {input_val}")

    def test_normalize_allergies_edge_cases(self):
        cases = [
            ("peanuts, milk", "peanuts, milk"),
            ("none", "none"),
            ("None", "none"),
            ("n/a", "none"),
            ("", "none"),
            ("peanuts\nmilk", "peanuts, milk"),
            ("milk; eggs", "milk, eggs"),
        ]
        for input_val, expected in cases:
            result = bot.normalize_allergies(input_val)
            self.assertEqual(result, expected, f"Failed for: {input_val}")

    def test_normalize_meal_dict_valid(self):
        raw = {
            "title": "Banana Oat Bowl",
            "ingredients": ["banana", "oats"],
            "quick_prep": "Mash",
            "safety_note": "Soft",
            "tags": ["fiber"],
        }
        result = bot.normalize_meal_dict(raw)
        self.assertEqual(result["title"], "Banana Oat Bowl")
        self.assertEqual(result["ingredients"], ["banana", "oats"])

    def test_normalize_meal_dict_missing_title_returns_none(self):
        raw = {"ingredients": ["banana"]}
        result = bot.normalize_meal_dict(raw)
        self.assertIsNone(result)

    def test_normalize_plan_dict_filters_invalid_meals(self):
        raw_plan = {
            "week_start_date": "2026-03-30",
            "days": {
                "mon": {
                    "breakfast": {"title": "Valid Meal", "ingredients": ["a"]},
                    "lunch": {"ingredients": ["missing title"]},
                }
            },
        }
        result = bot.normalize_plan_dict(raw_plan, week_start=bot.date(2026, 3, 30))
        self.assertIn("mon", result["days"])
        self.assertIn("breakfast", result["days"]["mon"])
        self.assertNotIn("lunch", result["days"]["mon"])

    def test_plan_has_content(self):
        self.assertFalse(bot.plan_has_content(None))
        self.assertFalse(bot.plan_has_content({"days": {}}))
        self.assertTrue(bot.plan_has_content({"days": {"mon": {"breakfast": {"title": "x"}}}}))

    def test_parse_json_object(self):
        self.assertEqual(
            bot.parse_json_object('```json\n{"key":"val"}\n```'),
            {"key": "val"},
        )
        self.assertEqual(
            bot.parse_json_object('{"key":"val"}'),
            {"key": "val"},
        )
        self.assertIsNone(bot.parse_json_object("not json"))
        self.assertIsNone(bot.parse_json_object(""))

    def test_parse_int_or_default(self):
        self.assertEqual(bot.parse_int_or_default("12", 10), 12)
        self.assertEqual(bot.parse_int_or_default("abc", 10), 10)
        self.assertEqual(bot.parse_int_or_default("3", 10), 4)
        self.assertEqual(bot.parse_int_or_default("37", 10), 36)


class RenderingTests(unittest.TestCase):
    def test_render_meal_card_has_required_elements(self):
        meal = {
            "title": "Banana Oat Bowl",
            "ingredients": ["banana", "oats"],
            "quick_prep": "Mash and serve",
            "safety_note": "Serve soft",
            "tags": ["fiber"],
        }
        card = bot.render_meal_card(meal, "breakfast")
        self.assertIn("🍽️", card)
        self.assertIn("Banana Oat Bowl", card)
        self.assertIn("📋", card)
        self.assertIn("⚡", card)

    def test_render_weekly_plan_empty(self):
        plan = {"days": {}}
        rendered = bot.render_weekly_plan(plan)
        self.assertIn("No meals planned", rendered)

    def test_render_weekly_plan_with_meals(self):
        plan = {
            "days": {
                "mon": {
                    "breakfast": {
                        "title": "Oatmeal",
                        "ingredients": ["oats", "banana"],
                        "quick_prep": "Mix",
                        "safety_note": "",
                        "tags": [],
                    }
                }
            }
        }
        rendered = bot.render_weekly_plan(plan)
        self.assertIn("Monday", rendered)
        self.assertIn("Oatmeal", rendered)

    def test_render_history_message_no_data(self):
        message = bot.render_history_message([], [])
        self.assertIn("Recent Plans", message)
        self.assertIn("No weekly plans", message)

    def test_render_history_message_with_data(self):
        plans = [{"week_start_date": "2026-03-30", "updated_at": "2026-03-29T10:00:00"}]
        inspirations = [{"kind": "photo", "summary": "Pasta inspiration"}]
        message = bot.render_history_message(plans, inspirations)
        self.assertIn("Week of 2026-03-30", message)
        self.assertIn("Pasta inspiration", message)

    def test_format_shopping_list_message(self):
        message = bot.format_shopping_list_message("Produce:\n- Apples")
        self.assertIn("Shopping List", message)
        self.assertIn("Apples", message)

    def test_format_inspiration_summary(self):
        self.assertEqual(
            bot.format_inspiration_summary("- Item 1\n- Item 2"),
            "• Item 1\n• Item 2",
        )
        self.assertEqual(
            bot.format_inspiration_summary("Single item"),
            "Single item",
        )

    def test_render_inspiration_message(self):
        text, keyboard = bot.render_inspiration_message(
            "- Pasta inspiration",
            [
                "Option 1 title\nLine 2\nLine 3",
                "Option 2 title\nLine 2",
            ],
        )
        self.assertIn("Option 1", text)
        self.assertIn("Option 2", text)
        self.assertIn("Use 1 for Wednesday dinner", text)
        self.assertEqual(len(keyboard.inline_keyboard), 2)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        bot.init_db()

    def test_upsert_user_and_get_profile_no_profile(self):
        bot.upsert_user(999001, "en")
        profile = bot.get_profile(999001)
        self.assertIsNone(profile)

    def test_set_and_get_profile(self):
        bot.upsert_user(999002, "en")
        bot.set_profile(999002, age_months=14, allergies="peanuts, milk")
        profile = bot.get_profile(999002)
        self.assertIsNotNone(profile)
        self.assertEqual(profile["age_months"], 14)
        self.assertEqual(profile["allergies"], "peanuts, milk")

    def test_store_and_get_inspiration(self):
        bot.upsert_user(999003, "en")
        inspiration_id = bot.store_inspiration(
            999003,
            kind="text",
            summary="Test inspiration",
            adaptations=["Option 1", "Option 2"],
        )
        self.assertIsNotNone(inspiration_id)
        inspiration = bot.get_inspiration(999003, inspiration_id)
        self.assertIsNotNone(inspiration)
        self.assertEqual(inspiration["summary"], "Test inspiration")

    def test_get_latest_inspiration(self):
        bot.upsert_user(999004, "en")
        bot.store_inspiration(999004, kind="text", summary="First", adaptations=[])
        bot.store_inspiration(999004, kind="text", summary="Second", adaptations=[])
        latest = bot.get_latest_inspiration(999004)
        self.assertEqual(latest["summary"], "Second")

    def test_upsert_weekly_plan(self):
        bot.upsert_user(999005, "en")
        week_start = bot.week_start_for_plans(bot.date.today())
        plan_json = json.dumps({"days": {}})
        plan_id = bot.upsert_weekly_plan(999005, week_start=week_start, plan_json=plan_json)
        self.assertIsNotNone(plan_id)
        plan = bot.get_weekly_plan(999005, week_start=week_start)
        self.assertIsNotNone(plan)

    def test_week_start_for_plans(self):
        from datetime import date
        ws = bot.week_start_for_plans(date(2026, 3, 28))
        self.assertEqual(str(ws), "2026-03-30")
        ws = bot.week_start_for_plans(date(2026, 3, 30))
        self.assertEqual(str(ws), "2026-04-06")


if __name__ == "__main__":
    unittest.main()