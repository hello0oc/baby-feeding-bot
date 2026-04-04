import pytest
from baby_feeding_bot import _split_text


class TestSplitText:
    def test_short_text_unchanged(self):
        text = "Hello, world!"
        assert _split_text(text, max_len=4000) == ["Hello, world!"]

    def test_exactly_at_limit(self):
        text = "a" * 4000
        assert _split_text(text, max_len=4000) == [text]

    def test_just_over_limit(self):
        text = "a" * 4001
        chunks = _split_text(text, max_len=4000)
        assert len(chunks) == 2
        assert len(chunks[0]) <= 4000
        assert len(chunks[1]) <= 4000
        assert chunks[0] + chunks[1] == text

    def test_prefers_newline_boundary(self):
        text = "line1\n" * 3000 + "final"
        chunks = _split_text(text, max_len=4000)
        # Should split at newlines
        for chunk in chunks:
            assert len(chunk) <= 4000
        # Verify no chunk ends mid-line if possible
        assert text.startswith(chunks[0])

    def test_splits_at_space_when_no_newline(self):
        text = " ".join(["word"] * 2000)
        chunks = _split_text(text, max_len=4000)
        for chunk in chunks:
            assert len(chunk) <= 4000

    def test_empty_text(self):
        assert _split_text("", max_len=4000) == []

    def test_multiple_chunks(self):
        text = "x" * 12000
        chunks = _split_text(text, max_len=4000)
        assert len(chunks) == 3
        for chunk in chunks:
            assert len(chunk) <= 4000
        assert "".join(chunks) == text
