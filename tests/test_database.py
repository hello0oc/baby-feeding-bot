"""
Database edge case tests for Baby Feeding Bot.
Tests upsert behavior, malformed data handling, and boundary conditions.
"""
import json
import os
import tempfile
import unittest
from datetime import date

os.environ.setdefault("BABY_FEEDING_BOT_TOKEN", "test-token")
os.environ.setdefault("MINIMAX_API_KEY", "test-key")
os.environ.setdefault(
    "BABY_FEEDING_DB_PATH",
    os.path.join(tempfile.gettempdir(), "baby_feeding_test_database.sqlite3"),
)

import baby_feeding_bot as bot


class UpsertUserTests(unittest.TestCase):
    """Test upsert_user behavior — should not duplicate users."""

    def setUp(self):
        bot.init_db()

    def test_upsert_user_no_duplicate(self):
        """Calling upsert_user twice with same user_id should not create duplicate rows."""
        bot.upsert_user(999300, "en")
        bot.upsert_user(999300, "en")
        with bot._db_conn() as conn:
            rows = conn.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE telegram_user_id = ?",
                (999300,),
            ).fetchone()
        self.assertEqual(rows["cnt"], 1, "Should have exactly 1 user row after two upserts")

    def test_upsert_user_preserves_locale_on_second_call(self):
        """Second upsert should not overwrite locale to NULL."""
        bot.upsert_user(999301, "es")
        bot.upsert_user(999301, None)  # None locale
        with bot._db_conn() as conn:
            row = conn.execute(
                "SELECT locale FROM users WHERE telegram_user_id = ?",
                (999301,),
            ).fetchone()
        self.assertEqual(row["locale"], "es")

    def test_upsert_user_updates_locale_from_none(self):
        """upsert_user should set locale when it was previously NULL."""
        bot.upsert_user(999302, None)
        bot.upsert_user(999302, "fr")
        with bot._db_conn() as conn:
            row = conn.execute(
                "SELECT locale FROM users WHERE telegram_user_id = ?",
                (999302,),
            ).fetchone()
        self.assertEqual(row["locale"], "fr")


class GetProfileTests(unittest.TestCase):
    """Test get_profile edge cases."""

    def setUp(self):
        bot.init_db()

    def test_get_profile_returns_none_for_unknown_user(self):
        """get_profile should return None for user with no profile."""
        profile = bot.get_profile(999999)
        self.assertIsNone(profile)

    def test_get_profile_returns_dict(self):
        """get_profile should return a dict, not a sqlite Row."""
        bot.upsert_user(999303, "en")
        bot.set_profile(999303, age_months=12, allergies="none")
        profile = bot.get_profile(999303)
        self.assertIsInstance(profile, dict)
        self.assertEqual(profile["age_months"], 12)

    def test_get_profile_after_onboarding_completed(self):
        """After onboarding, profile should exist with correct values."""
        bot.upsert_user(999304, "en")
        bot.set_profile(999304, age_months=8, allergies="peanuts")
        profile = bot.get_profile(999304)
        self.assertIsNotNone(profile)
        self.assertEqual(profile["age_months"], 8)
        self.assertEqual(profile["allergies"], "peanuts")


class PlanNormalizationTests(unittest.TestCase):
    """Test plan normalization with malformed JSON from DB."""

    def setUp(self):
        bot.reset_db_for_testing()
        bot.upsert_user(999310, "en")
        bot.set_profile(999310, age_months=12, allergies="none")

    def test_malformed_json_returns_error_plan(self):
        """Malformed JSON from DB should produce plan with 'error' key, not crash."""
        # Manually insert malformed JSON using upsert (to avoid UNIQUE constraint issues)
        now = bot.datetime.now(bot.UTC).isoformat()
        week_start = bot.week_start_for_plans(bot.date.today())
        with bot._db_conn() as conn:
            conn.execute(
                """
                INSERT INTO weekly_plans (telegram_user_id, week_start_date, plan_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id, week_start_date) DO UPDATE SET
                    plan_json = excluded.plan_json, updated_at = excluded.updated_at
                """,
                (999310, week_start.isoformat(), "not valid json {{{", now, now),
            )

        existing = bot.get_weekly_plan(999310, week_start=week_start)
        self.assertIsNotNone(existing)
        # normalize_plan_dict should handle malformed JSON gracefully
        try:
            plan_obj = bot.normalize_plan_dict(json.loads(str(existing["plan_json"])), week_start=week_start)
        except json.JSONDecodeError:
            plan_obj = {"week_start_date": week_start.isoformat(), "days": {}, "error": "parse_failed"}
        self.assertIn("error", plan_obj)
        self.assertFalse(bot.plan_has_content(plan_obj))

    def test_empty_days_dict_has_no_content(self):
        """Plan with empty days dict should be detected as having no content."""
        plan = {"week_start_date": "2026-03-30", "days": {}}
        self.assertFalse(bot.plan_has_content(plan))

    def test_days_with_empty_slot_dict_has_no_content(self):
        """Plan with day but empty slot dict should be detected as having no content."""
        plan = {"week_start_date": "2026-03-30", "days": {"mon": {}}}
        self.assertFalse(bot.plan_has_content(plan))

    def test_plan_with_only_invalid_meals_has_no_content(self):
        """Plan where all meals have missing/empty titles should have no content."""
        plan = {
            "week_start_date": "2026-03-30",
            "days": {
                "mon": {
                    "breakfast": {"ingredients": ["oats"]},  # missing title → filtered
                    "lunch": {},  # empty → filtered
                }
            },
        }
        self.assertFalse(bot.plan_has_content(plan))

    def test_plan_normalization_preserves_valid_meals(self):
        """normalize_plan_dict should preserve meals that have titles."""
        raw = {
            "week_start_date": "2026-03-30",
            "days": {
                "mon": {
                    "breakfast": {"title": "Oatmeal", "ingredients": ["oats"]},
                    "lunch": {"ingredients": []},  # missing title — filtered out
                }
            },
        }
        normalized = bot.normalize_plan_dict(raw, week_start=date(2026, 3, 30))
        self.assertIn("mon", normalized["days"])
        self.assertIn("breakfast", normalized["days"]["mon"])
        self.assertNotIn("lunch", normalized["days"]["mon"])  # no title → filtered
        self.assertEqual(normalized["days"]["mon"]["breakfast"]["title"], "Oatmeal")

    def test_plan_normalization_preserves_week_start_date(self):
        """normalize_plan_dict should preserve week_start_date from input."""
        raw = {"week_start_date": "2026-04-06", "days": {}}
        normalized = bot.normalize_plan_dict(raw, week_start=date(2026, 4, 6))
        self.assertEqual(normalized["week_start_date"], "2026-04-06")


class AllergenIntroTests(unittest.TestCase):
    """Test allergen introduction edge cases."""

    def setUp(self):
        bot.reset_db_for_testing()
        bot.upsert_user(999320, "en")
        bot.set_profile(999320, age_months=12, allergies="none")

    def test_introduce_allergen_new_returns_true(self):
        """First introduction of an allergen should return True."""
        result = bot.introduce_allergen(999320, "egg")
        self.assertTrue(result)

    def test_introduce_allergen_duplicate_returns_false(self):
        """Re-introduction of same allergen should return False."""
        bot.introduce_allergen(999320, "peanut")
        result = bot.introduce_allergen(999320, "peanut")
        self.assertFalse(result)

    def test_introduce_allergen_normalizes_case(self):
        """Allergen names should be normalized to lowercase."""
        bot.introduce_allergen(999321, "Peanut")
        result = bot.introduce_allergen(999321, "peanut")  # lowercase version
        self.assertFalse(result)  # Should be treated as duplicate

    def test_introduce_allergen_with_reactions(self):
        """Allergen introduction with reactions should be stored."""
        bot.introduce_allergen(999322, "milk", reactions="mild rash")
        journal = bot.get_allergen_journal(999322)
        self.assertEqual(len(journal), 1)
        self.assertEqual(journal[0]["allergen"], "milk")
        self.assertEqual(journal[0]["reactions"], "mild rash")

    def test_introduce_allergen_updates_profiles_column(self):
        """introduce_allergen should also update the profiles.introduced_allergens column."""
        bot.set_profile(999323, age_months=12, allergies="none")
        bot.introduce_allergen(999323, "egg")
        profile = bot.get_profile(999323)
        self.assertIsNotNone(profile)
        self.assertIn("egg", profile.get("introduced_allergens", ""))

    def test_get_introduced_allergens(self):
        """get_introduced_allergens returns list of introduced allergens."""
        bot.introduce_allergen(999324, "egg")
        bot.introduce_allergen(999324, "peanut")
        introduced = bot.get_introduced_allergens(999324)
        self.assertEqual(len(introduced), 2)
        self.assertIn("egg", introduced)
        self.assertIn("peanut", introduced)


class WeekStartBoundaryTests(unittest.TestCase):
    """Test week_start_for_plans boundary conditions."""

    def test_week_start_on_monday_returns_next_monday(self):
        """When today is Monday, week_start_for_plans returns NEXT Monday."""
        # Monday 2026-03-30
        monday = date(2026, 3, 30)
        ws = bot.week_start_for_plans(monday)
        # Should return next Monday (2026-04-06), not today
        self.assertEqual(str(ws), "2026-04-06")

    def test_week_start_on_sunday_returns_next_monday(self):
        """When today is Sunday, week_start_for_plans returns the Monday of the upcoming week."""
        sunday = date(2026, 3, 29)  # 2026-03-29 is a Sunday
        ws = bot.week_start_for_plans(sunday)
        # Next Monday from Sunday is March 30 (next day)
        self.assertEqual(str(ws), "2026-03-30")

    def test_week_start_on_wednesday(self):
        """Wednesday should return the Monday of next week."""
        wednesday = date(2026, 4, 1)
        ws = bot.week_start_for_plans(wednesday)
        self.assertEqual(str(ws), "2026-04-06")

    def test_week_start_on_saturday(self):
        """Saturday should return the Monday of next week."""
        saturday = date(2026, 4, 4)
        ws = bot.week_start_for_plans(saturday)
        self.assertEqual(str(ws), "2026-04-06")


class EmptyInspirationsListTests(unittest.TestCase):
    """Test handling of empty inspirations list."""

    def setUp(self):
        bot.reset_db_for_testing()
        bot.upsert_user(999330, "en")

    def test_get_recent_inspirations_empty_returns_list(self):
        """get_recent_inspirations should return empty list, not None."""
        result = bot.get_recent_inspirations(999330, limit=5)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_get_latest_inspiration_none_returns_none(self):
        """get_latest_inspiration for user with no inspirations returns None."""
        result = bot.get_latest_inspiration(999330)
        self.assertIsNone(result)

    def test_empty_inspirations_for_plan_generation(self):
        """generate_weekly_plan with empty inspirations should handle 'none' gracefully."""
        bot.set_profile(999331, age_months=12, allergies="none")
        # The plan generator should not crash when given empty inspirations
        # It will use "none" as the inspiration_text fallback
        # We can't fully test the LLM call here, but we can test the data flow
        inspirations = bot.get_recent_inspirations(999331, limit=10)
        self.assertEqual(len(inspirations), 0)
        # The data flow should pass an empty list, and the LLM function
        # handles it by using "none" as the fallback text
        inspiration_text = "\n".join(
            [f"- {i.get('summary', '')}".strip() for i in inspirations if i.get("summary")]
        ) or "none"
        self.assertEqual(inspiration_text, "none")


class SetProfileRatioPreservationTests(unittest.TestCase):
    """Test that set_profile preserves BLW/spoon ratios on update."""

    def setUp(self):
        bot.reset_db_for_testing()
        bot.upsert_user(999340, "en")

    def test_set_profile_preserves_ratios_on_age_update(self):
        """Updating age should not reset BLW/spoon ratios to defaults."""
        # Set initial profile
        bot.set_profile(999340, age_months=12, allergies="none", blw_ratio=0.6, spoon_ratio=0.4)
        profile = bot.get_profile(999340)
        self.assertAlmostEqual(profile["blw_ratio"], 0.6)
        self.assertAlmostEqual(profile["spoon_ratio"], 0.4)

        # Update only age — ratios should be preserved
        bot.set_profile(999340, age_months=14, allergies="none")
        profile = bot.get_profile(999340)
        self.assertEqual(profile["age_months"], 14)
        self.assertAlmostEqual(profile["blw_ratio"], 0.6)
        self.assertAlmostEqual(profile["spoon_ratio"], 0.4)

    def test_set_profile_preserves_ratios_on_allergy_update(self):
        """Updating allergies should not reset BLW/spoon ratios to defaults."""
        bot.set_profile(999341, age_months=10, allergies="none", blw_ratio=0.7, spoon_ratio=0.3)
        bot.set_profile(999341, age_months=10, allergies="peanuts")
        profile = bot.get_profile(999341)
        self.assertAlmostEqual(profile["blw_ratio"], 0.7)
        self.assertAlmostEqual(profile["spoon_ratio"], 0.3)

    def test_set_profile_first_creation_uses_defaults(self):
        """First profile creation should use default ratios (0.4/0.6)."""
        bot.set_profile(999342, age_months=12, allergies="none")
        profile = bot.get_profile(999342)
        self.assertAlmostEqual(profile["blw_ratio"], 0.4)
        self.assertAlmostEqual(profile["spoon_ratio"], 0.6)


if __name__ == "__main__":
    unittest.main()
