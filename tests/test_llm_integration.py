"""
Tier 4 LLM contract tests — mock httpx to test LLM integration without real API calls.
"""
import base64
import io
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("BABY_FEEDING_BOT_TOKEN", "test-token")
os.environ.setdefault("MINIMAX_API_KEY", "test-key")
os.environ.setdefault(
    "BABY_FEEDING_DB_PATH",
    os.path.join(tempfile.gettempdir(), "baby_feeding_test_llm.sqlite3"),
)

import baby_feeding_bot as bot
from PIL import Image


class LLMGenerateTests(unittest.IsolatedAsyncioTestCase):
    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_llm_generate_success(self, mock_post):
        """Mock 200 response with valid JSON returns text."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Banana Oatmeal\n- Mash banana\n- Add oats"}]
        }
        mock_post.return_value = mock_response

        result = await bot.llm_generate("Give me a baby meal idea")
        self.assertEqual(result, "Banana Oatmeal\n- Mash banana\n- Add oats")
        mock_post.assert_called_once()

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_llm_generate_400_error(self, mock_post):
        """Mock 400 response returns friendly error message."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        result = await bot.llm_generate("Give me a baby meal idea")
        self.assertIn("Sorry", result)
        self.assertIn("trouble", result)

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_llm_generate_blank_text(self, mock_post):
        """Mock 200 with empty content returns friendly error."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": [{"type": "text", "text": ""}]}
        mock_post.return_value = mock_response

        result = await bot.llm_generate("Give me a baby meal idea")
        self.assertIn("Sorry", result)

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_llm_generate_timeout(self, mock_post):
        """Mock timeout exception returns friendly error."""
        import httpx

        mock_post.side_effect = httpx.TimeoutException("Connection timeout")

        result = await bot.llm_generate("Give me a baby meal idea")
        self.assertIn("Sorry", result)

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_llm_generate_500_error(self, mock_post):
        """Mock 500 response returns friendly error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        result = await bot.llm_generate("Give me a baby meal idea")
        self.assertIn("Sorry", result)


class AnalyzeImageTests(unittest.IsolatedAsyncioTestCase):
    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_analyze_image_uses_vision_model(self, mock_post):
        """Capture request JSON, verify model is MiniMax-VL-01."""
        # Create a minimal valid image
        img = Image.new("RGB", (100, 100), color="red")
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG")
        image_bytes = buffered.getvalue()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": [{"type": "text", "text": "A red apple"}]}
        mock_post.return_value = mock_response

        result = await bot.analyze_image_for_inspiration(image_bytes, language="en")
        self.assertIn("red apple", result.lower())

        # Check the model used in the request
        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["model"], "MiniMax-VL-01")

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_analyze_image_includes_base64(self, mock_post):
        """Capture request JSON, verify image data is base64-encoded."""
        img = Image.new("RGB", (100, 100), color="blue")
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG")
        image_bytes = buffered.getvalue()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": [{"type": "text", "text": "A blue meal"}]}
        mock_post.return_value = mock_response

        await bot.analyze_image_for_inspiration(image_bytes, language="en")

        call_args = mock_post.call_args
        self.assertIsNotNone(call_args)
        payload = call_args.kwargs["json"]
        messages = payload["messages"]
        user_content = messages[0]["content"]
        image_block = next((b for b in user_content if b.get("type") == "image"), None)
        self.assertIsNotNone(image_block)
        self.assertEqual(image_block["source"]["type"], "base64")
        self.assertEqual(image_block["source"]["media_type"], "image/jpeg")
        # Decode and verify it's our image
        decoded = base64.b64decode(image_block["source"]["data"])
        self.assertTrue(decoded.startswith(b"\xff\xd8"))  # JPEG magic number


if __name__ == "__main__":
    unittest.main()
