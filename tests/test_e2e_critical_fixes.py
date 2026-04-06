#!/usr/bin/env python3
"""
E2E tests for the 4 critical bug fixes.
Tests the full user flow: weekly digest → day detail → adaptation → language correctness.

Run: python test_e2e_critical_fixes.py
"""
import io
import json
import os
import tempfile
import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("BABY_FEEDING_BOT_TOKEN", "test-token")
os.environ.setdefault("MINIMAX_API_KEY", "sk-test-key")
os.environ.setdefault(
    "BABY_FEEDING_DB_PATH",
    os.path.join(tempfile.gettempdir(), "baby_feeding_e2e_test.sqlite3"),
)

import baby_feeding_bot as bot
from PIL import Image


# =============================================================================
# FIX 1: Meal titles appear in weekly digest (was meal.get("name") → title)
# =============================================================================
class TestWeeklyDigestMealTitles(unittest.TestCase):
    """Regression test: meal titles must appear in the weekly digest icon strip."""

    def test_digest_shows_meal_titles_not_blank(self):
        """The icon strip summary should show actual food names, not '—'."""
        week_start = date(2026, 4, 6)
        plan = {
            "week_start_date": week_start.isoformat(),
            "days": {
                "mon": {
                    "breakfast": {
                        "title": "Banana Oat Porridge",
                        "ingredients": ["banana", "oats", "milk"],
                        "quick_prep": "Mash and mix",
                        "safety_note": "Suitable for 12mo+",
                        "tags": ["iron", "fiber"],
                    },
                    "snack1": {
                        "title": "Avocado strips",
                        "ingredients": ["avocado"],
                        "quick_prep": "Slice",
                        "safety_note": "",
                        "tags": [],
                    },
                    "lunch": {
                        "title": "Lentil vegetable mash",
                        "ingredients": ["lentils", "carrot", "broccoli"],
                        "quick_prep": "Blend",
                        "safety_note": "",
                        "tags": ["iron", "protein"],
                    },
                    "snack2": None,
                    "dinner": {
                        "title": "Sweet potato fingers",
                        "ingredients": ["sweet potato", "olive oil"],
                        "quick_prep": "Roast at 200C for 20min",
                        "safety_note": "",
                        "tags": ["vitamin-a"],
                    },
                },
                "tue": {
                    "breakfast": {
                        "title": "Eggy bread",
                        "ingredients": ["bread", "egg", "butter"],
                        "quick_prep": "Fry",
                        "safety_note": "",
                        "tags": ["protein"],
                    },
                    "snack1": None,
                    "lunch": None,
                    "snack2": None,
                    "dinner": None,
                },
            },
        }

        digest_en = bot.render_weekly_plan_digest(plan, language="en")
        digest_zh = bot.render_weekly_plan_digest(plan, language="zh")

        # Monday should show meal titles, not blank
        self.assertIn("Banana Oat Porridge", digest_en)
        self.assertIn("Avocado strips", digest_en)
        self.assertIn("Lentil vegetable mash", digest_en)
        # 4th meal shows as (+1 more) since we cap at 3
        self.assertIn("+1 more", digest_en)
        # Should NOT show blank dashes for filled slots
        self.assertNotIn("📆 Mon  🌅🍎🥗🧃🍲  —", digest_en)

        # Tuesday has only breakfast
        self.assertIn("Eggy bread", digest_en)
        self.assertIn("📆 Tue", digest_en)

        # Chinese mode — titles should still appear
        self.assertIn("Banana Oat Porridge", digest_zh)  # titles stay in English per LLM output lang

        print("✅ FIX 1: Meal titles appear in weekly digest")

    def test_digest_handles_missing_title_gracefully(self):
        """If meal has no title, should not crash."""
        plan = {
            "days": {
                "mon": {
                    "breakfast": {
                        # no title
                        "ingredients": ["carrot"],
                    },
                },
            },
        }
        digest = bot.render_weekly_plan_digest(plan, language="en")
        self.assertIn("📆 Mon", digest)
        print("✅ FIX 1: Handles missing title gracefully")


# =============================================================================
# FIX 2: Vision prompts respond in the user's language
# =============================================================================
class TestVisionPromptLanguage(unittest.TestCase):
    """Regression test: image analysis prompt must use user's language."""

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_vision_prompt_uses_english_for_en_user(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "A colorful vegetable stir-fry"}]
        }
        mock_post.return_value = mock_response

        img = Image.new("RGB", (100, 100), color="green")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        result = await bot.analyze_image_for_inspiration(buf.getvalue(), language="en")

        payload = mock_post.call_args.kwargs["json"]
        prompt_text = payload["messages"][0]["content"][0]["text"]
        self.assertIn("English", prompt_text)
        self.assertNotIn("Chinese", prompt_text)
        self.assertNotIn("Spanish", prompt_text)
        print("✅ FIX 2a: Vision prompt uses English for EN user")

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_vision_prompt_uses_chinese_for_zh_user(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "A colorful vegetable stir-fry"}]
        }
        mock_post.return_value = mock_response

        img = Image.new("RGB", (100, 100), color="green")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        result = await bot.analyze_image_for_inspiration(buf.getvalue(), language="zh")

        payload = mock_post.call_args.kwargs["json"]
        prompt_text = payload["messages"][0]["content"][0]["text"]
        self.assertIn("Chinese", prompt_text)
        self.assertNotIn("English", prompt_text)
        self.assertNotIn("Spanish", prompt_text)
        print("✅ FIX 2b: Vision prompt uses Chinese for ZH user")


# =============================================================================
# FIX 3: LLM adaptation + weekly plan prompts respond in user's language
# =============================================================================
class TestLLMPromptLanguage(unittest.TestCase):
    """Regression test: generate_two_adaptations and generate_weekly_plan must use user's language."""

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_adaptations_prompt_uses_chinese_for_zh(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Option 1\nChicken rice\nSoft"}]
        }
        mock_post.return_value = mock_response

        profile = {"age_months": 12, "allergies": "none"}
        await bot.generate_two_adaptations(
            inspiration="Chicken stir-fry with vegetables",
            profile=profile,
            language="zh",
        )

        payload = mock_post.call_args.kwargs["json"]
        last_user_message = payload["messages"][-1]["content"]
        self.assertIn("Chinese", last_user_message)
        self.assertNotIn("Spanish", last_user_message)
        print("✅ FIX 3a: Adaptations prompt uses Chinese for ZH user")

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_adaptations_prompt_uses_english_for_en(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Option 1\nChicken rice\nSoft"}]
        }
        mock_post.return_value = mock_response

        profile = {"age_months": 12, "allergies": "none"}
        await bot.generate_two_adaptations(
            inspiration="Chicken stir-fry with vegetables",
            profile=profile,
            language="en",
        )

        payload = mock_post.call_args.kwargs["json"]
        last_user_message = payload["messages"][-1]["content"]
        self.assertIn("English", last_user_message)
        self.assertNotIn("Spanish", last_user_message)
        self.assertNotIn("Chinese", last_user_message)
        print("✅ FIX 3b: Adaptations prompt uses English for EN user")

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_weekly_plan_prompt_uses_chinese_for_zh(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "week_start_date": "2026-04-06",
                    "days": {
                        "mon": {
                            "breakfast": {"title": "Oats", "ingredients": [], "quick_prep": "", "safety_note": "", "tags": []},
                            "snack1": None, "lunch": None, "snack2": None, "dinner": None,
                        }
                    },
                })
            }]
        }
        mock_post.return_value = mock_response

        week_start = date(2026, 4, 6)
        profile = {"age_months": 12, "allergies": "none"}
        await bot.generate_weekly_plan(
            profile=profile,
            inspirations=[],
            week_start=week_start,
            language="zh",
            telegram_user_id=0,
        )

        payload = mock_post.call_args.kwargs["json"]
        last_user_message = payload["messages"][-1]["content"]
        self.assertIn("Chinese", last_user_message)
        self.assertNotIn("Spanish", last_user_message)
        print("✅ FIX 3c: Weekly plan prompt uses Chinese for ZH user")

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_weekly_plan_prompt_uses_english_for_en(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "week_start_date": "2026-04-06",
                    "days": {
                        "mon": {
                            "breakfast": {"title": "Oats", "ingredients": [], "quick_prep": "", "safety_note": "", "tags": []},
                            "snack1": None, "lunch": None, "snack2": None, "dinner": None,
                        }
                    },
                })
            }]
        }
        mock_post.return_value = mock_response

        week_start = date(2026, 4, 6)
        profile = {"age_months": 12, "allergies": "none"}
        await bot.generate_weekly_plan(
            profile=profile,
            inspirations=[],
            week_start=week_start,
            language="en",
            telegram_user_id=0,
        )

        payload = mock_post.call_args.kwargs["json"]
        last_user_message = payload["messages"][-1]["content"]
        self.assertIn("English", last_user_message)
        self.assertNotIn("Spanish", last_user_message)
        self.assertNotIn("Chinese", last_user_message)
        print("✅ FIX 3d: Weekly plan prompt uses English for EN user")


# =============================================================================
# FIX 4: System prompt must NOT be corrupted with Spanish for ZH users
# =============================================================================
class TestSystemPromptIntegrity(unittest.TestCase):
    """Regression test: ZH users must get clean English system prompt, not Spanish."""

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_zh_user_system_prompt_not_spanish(self, mock_post):
        """For ZH users, the system prompt should NOT say 'Eres un asistente útil'."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Chicken rice with soft vegetables"}]
        }
        mock_post.return_value = mock_response

        profile = {"age_months": 12, "allergies": "none"}
        await bot.generate_two_adaptations(
            inspiration="Chicken stir-fry",
            profile=profile,
            language="zh",
        )

        payload = mock_post.call_args.kwargs["json"]
        system_message = payload["messages"][0]["content"]
        # System prompt should NOT contain Spanish
        self.assertNotIn("Eres", system_message)
        self.assertNotIn("asistente", system_message)
        self.assertNotIn("útil", system_message)
        # System prompt should be the clean English one
        self.assertIn("JSON-only", system_message)
        print("✅ FIX 4a: ZH user system prompt is clean English (not Spanish)")

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_zh_meal_generation_system_prompt_not_spanish(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "title": "Lentil mash",
                    "ingredients": ["lentils", "carrot"],
                    "quick_prep": "Blend",
                    "safety_note": "Suitable for 12mo+",
                    "tags": ["iron"],
                })
            }]
        }
        mock_post.return_value = mock_response

        profile = {"age_months": 12, "allergies": "none"}
        await bot.generate_meal_for_slot(
            profile=profile,
            inspiration_summary="Lentil dish",
            selected_adaptation="Make it soft and mild",
            day_key="mon",
            slot_key="lunch",
            language="zh",
        )

        payload = mock_post.call_args.kwargs["json"]
        system_message = payload["messages"][0]["content"]
        self.assertNotIn("Eres", system_message)
        self.assertNotIn("asistente", system_message)
        self.assertIn("JSON-only", system_message)
        print("✅ FIX 4b: ZH meal generation system prompt is clean English")

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_zh_weekly_plan_system_prompt_not_spanish(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "week_start_date": "2026-04-06",
                    "days": {
                        "mon": {
                            "breakfast": {"title": "Oats", "ingredients": [], "quick_prep": "", "safety_note": "", "tags": []},
                            "snack1": None, "lunch": None, "snack2": None, "dinner": None,
                        }
                    },
                })
            }]
        }
        mock_post.return_value = mock_response

        week_start = date(2026, 4, 6)
        profile = {"age_months": 12, "allergies": "none"}
        await bot.generate_weekly_plan(
            profile=profile,
            inspirations=[],
            week_start=week_start,
            language="zh",
            telegram_user_id=0,
        )

        payload = mock_post.call_args.kwargs["json"]
        system_message = payload["messages"][0]["content"]
        self.assertNotIn("Eres", system_message)
        self.assertNotIn("asistente", system_message)
        self.assertIn("JSON-only", system_message)
        print("✅ FIX 4c: ZH weekly plan system prompt is clean English")


# =============================================================================
# BONUS: End-to-end flow test — weekly plan digest + day detail + keyboard
# =============================================================================
class TestEndToEndWeeklyFlow(unittest.TestCase):
    """Simulate the full weekly plan flow: digest → day detail → back to digest."""

    @classmethod
    def setUpClass(cls):
        import baby_feeding_bot as _bot
        _bot.init_db()

    def test_full_week_flow_en(self):
        week_start = date(2026, 4, 6)
        plan = {
            "week_start_date": week_start.isoformat(),
            "days": {
                "mon": {
                    "breakfast": {
                        "title": "Banana Oat Porridge",
                        "ingredients": ["banana", "oats", "milk"],
                        "quick_prep": "Mash and mix",
                        "safety_note": "Suitable for 12mo+",
                        "tags": ["iron", "fiber"],
                    },
                    "snack1": None,
                    "lunch": {
                        "title": "Chicken rice",
                        "ingredients": ["chicken", "rice", "broccoli"],
                        "quick_prep": "Steam and shred",
                        "safety_note": "",
                        "tags": ["protein", "iron"],
                    },
                    "snack2": None,
                    "dinner": {
                        "title": "Vegetable puree",
                        "ingredients": ["carrot", "potato", "peas"],
                        "quick_prep": "Boil and blend",
                        "safety_note": "",
                        "tags": ["vitamin-a", "fiber"],
                    },
                },
                "tue": {
                    "breakfast": {
                        "title": "Scrambled eggs on toast",
                        "ingredients": ["egg", "bread", "butter"],
                        "quick_prep": "Fry eggs, toast bread",
                        "safety_note": "Well-cooked eggs only",
                        "tags": ["protein"],
                    },
                    "snack1": {"title": "Pear slices", "ingredients": ["pear"], "quick_prep": "Slice", "safety_note": "", "tags": []},
                    "lunch": None,
                    "snack2": None,
                    "dinner": None,
                },
            },
        }
        profile = {"age_months": 12, "allergies": "none"}

        # Step 1: Full week digest
        digest = bot.render_weekly_plan_digest(plan, language="en", profile=profile)
        self.assertIn("Banana Oat Porridge", digest)
        self.assertIn("📆 Mon", digest)
        self.assertIn("📆 Tue", digest)
        self.assertIn("🌅", digest)  # breakfast icon

        # Step 2: Day detail for Monday
        detail_mon = bot.render_day_detail(plan, "mon", language="en", profile=profile)
        self.assertIn("Mon", detail_mon)
        self.assertIn("Banana Oat Porridge", detail_mon)
        self.assertIn("Chicken rice", detail_mon)
        self.assertIn("Vegetable puree", detail_mon)

        # Step 3: Day detail for Tuesday
        detail_tue = bot.render_day_detail(plan, "tue", language="en", profile=profile)
        self.assertIn("Tue", detail_tue)
        self.assertIn("Scrambled eggs on toast", detail_tue)
        self.assertIn("Pear slices", detail_tue)

        # Step 4: Keyboard has correct day buttons
        kb = bot.build_weekly_plan_keyboard(language="en")
        buttons = {b.text: b.callback_data for row in kb.inline_keyboard for b in row}
        self.assertEqual(buttons["📆 Mon"], "day_mon")
        self.assertEqual(buttons["📆 Tue"], "day_tue")
        self.assertEqual(buttons["📆 Wed"], "day_wed")
        self.assertEqual(buttons["📋 Full week"], "fullweek")
        self.assertEqual(buttons["🌐 EN"], "lang:en")
        self.assertEqual(buttons["ZH"], "lang:zh")

        # Step 5: ZH keyboard uses Chinese day names
        kb_zh = bot.build_weekly_plan_keyboard(language="zh")
        zh_buttons = {b.text: b.callback_data for row in kb_zh.inline_keyboard for b in row}
        self.assertEqual(zh_buttons["📆 周一"], "day_mon")
        self.assertEqual(zh_buttons["📆 周二"], "day_tue")
        self.assertEqual(zh_buttons["📋 完整周"], "fullweek")
        self.assertEqual(zh_buttons["🌐 EN"], "lang:en")
        self.assertEqual(zh_buttons["ZH"], "lang:zh")

        print("✅ E2E: Full weekly flow — digest, day detail, keyboard all working")

    def test_empty_day_shows_no_meals(self):
        """Day with no meals should show '—' not crash."""
        plan = {
            "days": {
                "wed": {
                    "breakfast": None,
                    "snack1": None,
                    "lunch": None,
                    "snack2": None,
                    "dinner": None,
                },
            },
        }
        digest = bot.render_weekly_plan_digest(plan, language="en")
        self.assertIn("📆 Wed", digest)
        # Should not show meal titles
        self.assertNotIn("Banana", digest)
        print("✅ E2E: Empty days handled gracefully")


if __name__ == "__main__":
    import unittest
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestWeeklyDigestMealTitles))
    suite.addTests(loader.loadTestsFromTestCase(TestVisionPromptLanguage))
    suite.addTests(loader.loadTestsFromTestCase(TestLLMPromptLanguage))
    suite.addTests(loader.loadTestsFromTestCase(TestSystemPromptIntegrity))
    suite.addTests(loader.loadTestsFromTestCase(TestEndToEndWeeklyFlow))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    if result.wasSuccessful():
        print(f"🎉 ALL {result.testsRun} E2E TESTS PASSED")
    else:
        print(f"❌ {len(result.failures)} failures, {len(result.errors)} errors")
        for test, trace in result.failures + result.errors:
            print(f"\n--- {test} ---")
            print(trace)
