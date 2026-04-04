import os
import tempfile
import pytest

os.environ.setdefault("BABY_FEEDING_BOT_TOKEN", "test-token")
os.environ.setdefault("MINIMAX_API_KEY", "test-key")
os.environ.setdefault("BABY_FEEDING_DB_PATH", os.path.join(tempfile.gettempdir(), "test_shopping.sqlite3"))

from baby_feeding_bot import _render_shopping_list_from_json


class TestShoppingListRenderer:
    def test_valid_json_parsed_correctly(self):
        raw = '{"produce": ["3× carrots", "banana"], "protein": ["chicken"], "dairy": [], "pantry": [], "other": []}'
        result = _render_shopping_list_from_json(raw, "en")
        assert "🛒" in result
        assert "🥦" in result
        assert "3× carrots" in result
        assert "chicken" in result

    def test_markdown_fence_stripped(self):
        raw = '```json\n{"produce": ["apple"], "protein": [], "dairy": ["yogurt"], "pantry": [], "other": []}\n```'
        result = _render_shopping_list_from_json(raw, "en")
        assert "🛒" in result
        assert "apple" in result

    def test_empty_categories_omitted(self):
        raw = '{"produce": ["carrot"], "protein": [], "dairy": [], "pantry": [], "other": []}'
        result = _render_shopping_list_from_json(raw, "en")
        assert "🥦" in result
        assert "🥩" not in result
        assert "🧀" not in result

    def test_raw_text_fallback(self):
        raw = "Here is my shopping list:\ncarrots\napples"
        result = _render_shopping_list_from_json(raw, "en")
        assert "🛒" in result
        assert "carrots" in result

    def test_spanish_header(self):
        raw = '{"produce": ["zanahoria"], "protein": [], "dairy": [], "pantry": [], "other": []}'
        result = _render_shopping_list_from_json(raw, "es")
        assert "🛒 Lista de Compras" in result
