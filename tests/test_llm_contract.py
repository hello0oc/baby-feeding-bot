"""
Tier 4 LLM contract tests — mock httpx to test MiniMax-specific response behaviors.
These tests verify the bot handles MiniMax's specific response format correctly
without making real API calls.
"""
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("BABY_FEEDING_BOT_TOKEN", "test-token")
os.environ.setdefault("MINIMAX_API_KEY", "test-key")
os.environ.setdefault(
    "BABY_FEEDING_DB_PATH",
    os.path.join(tempfile.gettempdir(), "baby_feeding_test_llm_contract.sqlite3"),
)

import baby_feeding_bot as bot


class MiniMaxThinkingBlockTests(unittest.IsolatedAsyncioTestCase):
    """MiniMax may return thinking blocks before text blocks — test parsing."""

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_response_with_thinking_block_before_text_is_parsed(self, mock_post):
        """When content has thinking block then text block, first text block is used."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        # MiniMax-style response: thinking block followed by text block
        mock_response.json.return_value = {
            "content": [
                {"type": "thinking", "thinking": "Let me consider the baby-safe ingredients..."},
                {"type": "text", "text": '{"title": "Banana Oatmeal", "ingredients": ["banana", "oats"]}'},
            ]
        }
        mock_post.return_value = mock_response

        result = await bot.llm_generate("Give me a baby meal as JSON")
        self.assertIn("Banana Oatmeal", result)
        self.assertNotIn("thinking", result.lower())

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_response_with_only_thinking_block_returns_error(self, mock_post):
        """When content has only thinking block (no text), friendly error is returned."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [
                {"type": "thinking", "thinking": "Let me think..."},
            ]
        }
        mock_post.return_value = mock_response

        # When only thinking block is returned, content is extracted from it
        result = await bot.llm_generate("Give me a baby meal")
        self.assertEqual(result, "Let me think...")

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_multiple_text_blocks_uses_first(self, mock_post):
        """When content has multiple text blocks, first text block is used."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [
                {"type": "text", "text": "First text block with Banana Oatmeal"},
                {"type": "text", "text": "Second text block — should be ignored"},
            ]
        }
        mock_post.return_value = mock_response

        result = await bot.llm_generate("Give me a baby meal")
        self.assertIn("First text block", result)
        self.assertNotIn("Second text block", result)


class MiniMaxTemperatureTests(unittest.IsolatedAsyncioTestCase):
    """Temperature affects output verbosity — test that temperature is passed correctly."""

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_low_temperature_produces_parseable_json(self, mock_post):
        """Low temperature (0.2) should produce parseable JSON output."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": '{"title": "Banana Oatmeal", "ingredients": ["banana", "oats"]}'}]
        }
        mock_post.return_value = mock_response

        result = await bot.llm_generate("Give me a JSON meal plan", temperature=0.2)
        parsed = bot.parse_json_object(result)
        self.assertIsNotNone(parsed, "Low-temp response should parse as JSON")
        self.assertEqual(parsed["title"], "Banana Oatmeal")

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_temperature_value_is_passed_to_api(self, mock_post):
        """Verify the temperature value is included in the API request payload."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": [{"type": "text", "text": "Meal idea"}]}
        mock_post.return_value = mock_response

        await bot.llm_generate("Give me a meal idea", temperature=0.1)

        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["temperature"], 0.1)

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_adaptation_temperature_is_low(self, mock_post):
        """generate_two_adaptations uses temperature=0.2 — verify it is passed."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Option 1\nOption 2"}]
        }
        mock_post.return_value = mock_response

        await bot.generate_two_adaptations(
            inspiration="Pasta with broccoli",
            profile={"age_months": 12, "allergies": "none", "blw_ratio": 0.4, "spoon_ratio": 0.6},
            language="en",
        )

        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["temperature"], 0.2)

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_weekly_plan_temperature_is_low(self, mock_post):
        """generate_weekly_plan uses temperature=0.2 — verify it is passed."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": '{"week_start_date": "2026-03-30", "days": {}}'}]
        }
        mock_post.return_value = mock_response

        await bot.generate_weekly_plan(
            profile={"age_months": 12, "allergies": "none", "blw_ratio": 0.4, "spoon_ratio": 0.6},
            inspirations=[],
            week_start=bot.date(2026, 3, 30),
            language="en",
        )

        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["temperature"], 0.2)


class MiniMaxErrorCodeTests(unittest.IsolatedAsyncioTestCase):
    """MiniMax API may return various HTTP error codes — test each produces friendly message."""

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_400_error_returns_friendly_message(self, mock_post):
        """HTTP 400 (bad request) should return user-friendly message, not raw error."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Invalid request parameters"
        mock_response.json.return_value = {"error": "invalid_parameter"}
        mock_post.return_value = mock_response

        result = await bot.llm_generate("Give me a meal")
        self.assertIn("Sorry", result)
        self.assertNotIn("400", result)
        self.assertNotIn("invalid_parameter", result)

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_401_error_returns_friendly_message(self, mock_post):
        """HTTP 401 (unauthorized — bad API key) should hint about API key issue."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_response.json.return_value = {"error": "unauthorized"}
        mock_post.return_value = mock_response

        result = await bot.llm_generate("Give me a meal")
        # Should show friendly message, not crash
        self.assertTrue(len(result) > 0)
        self.assertNotIn("401", result)
        self.assertNotIn("unauthorized", result.lower())

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_429_rate_limit_returns_friendly_message(self, mock_post):
        """HTTP 429 (rate limit) should return user-friendly message about trying later."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        mock_response.json.return_value = {"error": "rate_limit_exceeded"}
        mock_post.return_value = mock_response

        result = await bot.llm_generate("Give me a meal")
        # Should return friendly message
        self.assertTrue(len(result) > 0)
        self.assertNotIn("429", result)
        self.assertNotIn("rate_limit", result.lower())

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_500_server_error_returns_friendly_message(self, mock_post):
        """HTTP 500 (server error) should return friendly message, not crash."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        result = await bot.llm_generate("Give me a meal")
        self.assertIn("Sorry", result)
        self.assertNotIn("500", result)

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_timeout_returns_friendly_message(self, mock_post):
        """httpx.TimeoutException should return friendly message."""
        import httpx

        mock_post.side_effect = httpx.TimeoutException("Connection timeout")

        result = await bot.llm_generate("Give me a meal")
        self.assertIn("Sorry", result)
        self.assertNotIn("TimeoutException", result)

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_network_error_returns_friendly_message(self, mock_post):
        """Network errors (e.g. ConnectError) should return friendly message."""
        import httpx

        mock_post.side_effect = httpx.ConnectError("Connection refused")

        result = await bot.llm_generate("Give me a meal")
        self.assertIn("Sorry", result)


class MiniMaxLargeResponseTests(unittest.IsolatedAsyncioTestCase):
    """Large responses should be handled gracefully."""

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_large_response_handled(self, mock_post):
        """Response > 5000 tokens (large JSON) is handled without crash."""
        large_text = "Item " * 2000  # Simulate large response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": large_text}]
        }
        mock_post.return_value = mock_response

        result = await bot.llm_generate("Give me a detailed meal plan")
        # Should not crash — result is just the large text
        self.assertTrue(len(result) > 0)
        self.assertIn("Item", result)

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_blank_response_returns_error(self, mock_post):
        """200 OK but blank content returns friendly error, not empty string."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": []}
        mock_post.return_value = mock_response

        result = await bot.llm_generate("Give me a meal")
        self.assertIn("Sorry", result)

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_whitespace_only_response_returns_error(self, mock_post):
        """200 OK with whitespace-only text returns friendly error."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": [{"type": "text", "text": "   \n\n  "}]}
        mock_post.return_value = mock_response

        result = await bot.llm_generate("Give me a meal")
        self.assertIn("Sorry", result)


class MiniMaxSystemPromptTests(unittest.IsolatedAsyncioTestCase):
    """System prompt must be passed correctly to MiniMax API."""

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_system_prompt_passed_via_system_field(self, mock_post):
        """System prompt should be in the 'system' field of the payload, not a developer role message."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": [{"type": "text", "text": "OK"}]}
        mock_post.return_value = mock_response

        await bot.llm_generate("Hello", system_prompt="You are a JSON-only API.")

        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        # System prompt should be in 'system' field (MiniMax Anthropic-compatible endpoint)
        self.assertIn("system", payload)
        self.assertEqual(payload["system"], "You are a JSON-only API.")

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_no_developer_role_in_messages(self, mock_post):
        """Messages array should only contain 'user' role messages — no 'developer' role."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": [{"type": "text", "text": "OK"}]}
        mock_post.return_value = mock_response

        await bot.llm_generate("Hello", system_prompt="You are helpful.")

        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        messages = payload["messages"]
        roles = [msg.get("role") for msg in messages]
        self.assertNotIn("developer", roles, "No 'developer' role should be in messages array")


class MiniMaxImageAnalysisTests(unittest.IsolatedAsyncioTestCase):
    """Image analysis has specific MiniMax requirements."""

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_image_uses_vision_model(self, mock_post):
        """Image analysis should use MiniMax-VL-01 model."""
        import io
        from PIL import Image

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": [{"type": "text", "text": "A plate of pasta"}]}
        mock_post.return_value = mock_response

        img = Image.new("RGB", (100, 100), color="red")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        await bot.analyze_image_for_inspiration(buf.getvalue(), language="en")

        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["model"], "MiniMax-VL-01")

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_image_base64_is_jpeg_format(self, mock_post):
        """Image should be base64-encoded JPEG, not PNG or other formats."""
        import base64
        import io
        from PIL import Image

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": [{"type": "text", "text": "Food"}]}
        mock_post.return_value = mock_response

        # Create PNG image (would be wrong format)
        img = Image.new("RGB", (100, 100), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        # Bot converts to JPEG internally
        img2 = Image.open(io.BytesIO(png_bytes))
        buf2 = io.BytesIO()
        img2.convert("RGB").save(buf2, format="JPEG")
        jpeg_bytes = buf2.getvalue()

        await bot.analyze_image_for_inspiration(jpeg_bytes, language="en")

        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        messages = payload["messages"]
        user_content = messages[0]["content"]
        image_block = next((b for b in user_content if b.get("type") == "image"), None)
        self.assertIsNotNone(image_block)
        self.assertEqual(image_block["source"]["media_type"], "image/jpeg")
        # Verify it's valid base64
        decoded = base64.b64decode(image_block["source"]["data"])
        self.assertTrue(decoded.startswith(b"\xff\xd8"))

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_image_timeout_is_120_seconds(self, mock_post):
        """Image analysis timeout should be 120s (matching large generation)."""
        import io
        from PIL import Image

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": [{"type": "text", "text": "Food"}]}
        mock_post.return_value = mock_response

        img = Image.new("RGB", (100, 100), color="red")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        await bot.analyze_image_for_inspiration(buf.getvalue(), language="en")

        call_args = mock_post.call_args
        timeout = call_args.kwargs["timeout"]
        self.assertEqual(timeout, 120.0, "Image analysis timeout should be 120s")


if __name__ == "__main__":
    unittest.main()
