import os
import tempfile
import unittest

os.environ.setdefault("BABY_FEEDING_BOT_TOKEN", "test-token")
os.environ.setdefault("MINIMAX_API_KEY", "test-key")
os.environ.setdefault(
    "BABY_FEEDING_DB_PATH",
    os.path.join(tempfile.gettempdir(), "baby_feeding_test_helpers.sqlite3"),
)

import baby_feeding_bot as bot


class HelperTests(unittest.TestCase):
    def test_parse_quick_apply_text(self):
        self.assertEqual(bot.parse_quick_apply_text("Use 1 for Wednesday dinner"), (1, "wed", "dinner"))
        self.assertEqual(bot.parse_quick_apply_text("apply 2 to mon snack 1"), (2, "mon", "snack1"))
        self.assertEqual(bot.parse_quick_apply_text("Use 2 for Friday lunch"), (2, "fri", "lunch"))
        self.assertIsNone(bot.parse_quick_apply_text("Invalid text"))
        self.assertIsNone(bot.parse_quick_apply_text("Use 3 for Monday dinner"))

    def test_parse_json_object_from_fenced_block(self):
        text = 'Here you go\n```json\n{"title":"Oatmeal","ingredients":["oats"]}\n```'
        parsed = bot.parse_json_object(text)
        self.assertEqual(parsed, {"title": "Oatmeal", "ingredients": ["oats"]})

    def test_parse_json_object_from_raw(self):
        text = '{"title":"Oatmeal","ingredients":["oats"]}'
        parsed = bot.parse_json_object(text)
        self.assertEqual(parsed, {"title": "Oatmeal", "ingredients": ["oats"]})

    def test_parse_json_object_invalid(self):
        self.assertIsNone(bot.parse_json_object("not json at all"))
        self.assertIsNone(bot.parse_json_object(""))
        self.assertIsNone(bot.parse_json_object(None))

    def test_normalize_meal_dict_full(self):
        raw = {
            "title": "Banana Oat Bowl",
            "ingredients": ["banana", "oats"],
            "quick_prep": "Mash and serve",
            "safety_note": "Serve soft",
            "tags": ["fiber", "iron-rich"],
        }
        normalized = bot.normalize_meal_dict(raw)
        self.assertEqual(normalized["title"], "Banana Oat Bowl")
        self.assertEqual(normalized["ingredients"], ["banana", "oats"])
        self.assertEqual(normalized["quick_prep"], "Mash and serve")
        self.assertEqual(normalized["safety_note"], "Serve soft")
        self.assertEqual(normalized["tags"], ["fiber", "iron-rich"])

    def test_normalize_meal_dict_missing_title(self):
        raw = {"ingredients": ["banana", "oats"]}
        self.assertIsNone(bot.normalize_meal_dict(raw))

    def test_normalize_meal_dict_string_ingredients(self):
        raw = {"title": "Soup", "ingredients": "peas, carrots"}
        normalized = bot.normalize_meal_dict(raw)
        self.assertEqual(normalized["ingredients"], ["peas", "carrots"])

    def test_normalize_plan_dict_filters_invalid_meals(self):
        raw_plan = {
            "week_start_date": "2026-03-30",
            "days": {
                "mon": {
                    "breakfast": {
                        "title": "Banana Oat Bowl",
                        "ingredients": ["banana", "oats"],
                        "quick_prep": "Mash and serve",
                        "safety_note": "Serve soft",
                        "tags": ["fiber"],
                    },
                    "lunch": {"ingredients": ["missing title"]},
                },
                "wed": {"dinner": {"title": "Soup", "ingredients": "peas, carrots"}},
            },
        }
        normalized = bot.normalize_plan_dict(raw_plan, week_start=bot.date(2026, 3, 30))
        self.assertIn("mon", normalized["days"])
        self.assertIn("wed", normalized["days"])
        self.assertNotIn("lunch", normalized["days"]["mon"])
        self.assertEqual(normalized["days"]["wed"]["dinner"]["ingredients"], ["peas", "carrots"])

    def test_normalize_plan_dict_handles_full_day_names(self):
        """normalize_plan_dict should accept full day names from LLM (e.g. 'Monday')."""
        raw_plan = {
            "week_start_date": "2026-03-30",
            "days": {
                "Monday": {
                    "breakfast": {"title": "Oatmeal", "ingredients": ["oats", "banana"]},
                    "lunch": {"title": "Veggie Puree", "ingredients": ["carrot", "pea"]},
                },
                "Wednesday": {
                    "dinner": {"title": "Fish", "ingredients": ["cod", "sweet potato"]},
                },
            },
        }
        normalized = bot.normalize_plan_dict(raw_plan, week_start=bot.date(2026, 3, 30))
        self.assertIn("mon", normalized["days"])
        self.assertIn("wed", normalized["days"])
        self.assertIn("breakfast", normalized["days"]["mon"])
        self.assertIn("lunch", normalized["days"]["mon"])
        self.assertIn("dinner", normalized["days"]["wed"])
        self.assertEqual(normalized["days"]["mon"]["breakfast"]["title"], "Oatmeal")
        self.assertEqual(normalized["days"]["wed"]["dinner"]["title"], "Fish")

    def test_normalize_plan_dict_handles_mixed_day_names(self):
        """normalize_plan_dict should handle a mix of abbreviated and full day names."""
        raw_plan = {
            "week_start_date": "2026-04-06",
            "days": {
                "mon": {"breakfast": {"title": "Porridge", "ingredients": ["oats"]}},
                "Tuesday": {"lunch": {"title": "Soup", "ingredients": ["broth"]}},
                "wed": {"snack1": {"title": "Apple", "ingredients": ["apple"]}},
            },
        }
        normalized = bot.normalize_plan_dict(raw_plan, week_start=bot.date(2026, 4, 6))
        self.assertIn("mon", normalized["days"])
        self.assertIn("tue", normalized["days"])
        self.assertIn("wed", normalized["days"])

    def test_render_inspiration_message_is_actionable(self):
        text, keyboard = bot.render_inspiration_message(
            "- Pasta bake inspiration",
            [
                "Creamy Veggie Pasta\nIngredients: pasta, broccoli\nQuick prep: steam and mix\nSafety note: chop finely",
                "Chicken Rice Bowl\nIngredients: chicken, rice\nQuick prep: shred and stir\nSafety note: serve warm",
            ],
        )
        self.assertIn("Use 1 for Wednesday dinner", text)
        self.assertIn("Option 1", text)
        self.assertIn("Option 2", text)
        # Verify keyboard has option picker
        self.assertEqual(len(keyboard.inline_keyboard), 2)
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "opt:1")
        self.assertEqual(keyboard.inline_keyboard[1][0].callback_data, "opt:2")

    def test_render_inspiration_message_spanish(self):
        text, keyboard = bot.render_inspiration_message(
            "- Pasta bake inspiration",
            ["Creamy Veggie Pasta", "Chicken Rice Bowl"],
            language="es",
        )
        self.assertIn("Opción 1", text)
        self.assertIn("Esto es lo que encontré", text)

    def test_render_meal_card_formatting(self):
        meal = {
            "title": "Banana Oat Bowl",
            "ingredients": ["banana", "oats", "milk"],
            "quick_prep": "Mash and serve",
            "safety_note": "Serve soft",
            "tags": ["fiber", "iron-rich"],
        }
        card = bot.render_meal_card(meal, "breakfast")
        self.assertIn("🍽️  Banana Oat Bowl", card)
        self.assertIn("📋", card)
        self.assertIn("⚡", card)
        self.assertIn("⚠️", card)

    def test_render_weekly_plan_formatting(self):
        plan = {
            "week_start_date": "2026-03-30",
            "days": {
                "mon": {
                    "breakfast": {
                        "title": "Banana Oat Bowl",
                        "ingredients": ["banana", "oats"],
                        "quick_prep": "Mash",
                        "safety_note": "Soft",
                        "tags": ["fiber"],
                    }
                }
            },
        }
        rendered = bot.render_weekly_plan(plan)
        self.assertIn("📅 Weekly Plan", rendered)
        self.assertIn("📆 Monday", rendered)
        self.assertIn("🍽️", rendered)

    def test_render_history_message_formatting(self):
        plans = [{"week_start_date": "2026-03-30", "updated_at": "2026-03-29T10:00:00"}]
        inspirations = [{"kind": "photo", "summary": "Pasta inspiration"}]
        message = bot.render_history_message(plans, inspirations)
        self.assertIn("📚 Recent Plans", message)
        self.assertIn("💡 Recent Inspirations", message)
        self.assertIn("Week of 2026-03-30", message)

    def test_format_shopping_list_message(self):
        list_text = "Produce:\n- Apples\n- Carrots"
        message = bot.format_shopping_list_message(list_text)
        self.assertIn("🛒 Shopping List", message)
        self.assertIn("Produce", message)

    def test_format_shopping_list_message_empty(self):
        message = bot.format_shopping_list_message("")
        self.assertIn("couldn't build", message.lower())

    def test_plan_has_content(self):
        empty_plan = {"days": {}}
        self.assertFalse(bot.plan_has_content(empty_plan))
        self.assertFalse(bot.plan_has_content(None))

        full_plan = {"days": {"mon": {"breakfast": {"title": "Test"}}}}
        self.assertTrue(bot.plan_has_content(full_plan))

    def test_normalize_day(self):
        self.assertEqual(bot.normalize_day("monday"), "mon")
        self.assertEqual(bot.normalize_day("mon"), "mon")
        self.assertEqual(bot.normalize_day("wednesday"), "wed")
        self.assertIsNone(bot.normalize_day("invalid"))

    def test_normalize_slot(self):
        self.assertEqual(bot.normalize_slot("breakfast"), "breakfast")
        self.assertEqual(bot.normalize_slot("morning snack"), "snack1")
        self.assertEqual(bot.normalize_slot("snack1"), "snack1")
        self.assertEqual(bot.normalize_slot("afternoon snack"), "snack2")
        self.assertEqual(bot.normalize_slot("dinner"), "dinner")
        self.assertIsNone(bot.normalize_slot("invalid"))

    def test_normalize_allergies(self):
        self.assertEqual(bot.normalize_allergies("peanuts, milk"), "peanuts, milk")
        self.assertEqual(bot.normalize_allergies("none"), "none")
        self.assertEqual(bot.normalize_allergies("None"), "none")
        self.assertEqual(bot.normalize_allergies(""), "none")
        self.assertEqual(bot.normalize_allergies("peanuts\nmilk"), "peanuts, milk")

    def test_parse_int_or_default(self):
        self.assertEqual(bot.parse_int_or_default("12", 10), 12)
        self.assertEqual(bot.parse_int_or_default("abc", 10), 10)
        self.assertEqual(bot.parse_int_or_default("", 10), 10)
        self.assertEqual(bot.parse_int_or_default("3", 10), 4)
        self.assertEqual(bot.parse_int_or_default("37", 10), 36)
        self.assertEqual(bot.parse_int_or_default("18", 10), 18)


if __name__ == "__main__":
    unittest.main()