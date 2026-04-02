"""
Pytest fixtures for Baby Feeding Bot tests.
"""
import io
import os
import tempfile

import pytest


@pytest.fixture
def mock_profile():
    """Standard profile dict for testing."""
    return {
        "telegram_user_id": 12345,
        "age_months": 12,
        "allergies": "none",
        "blw_ratio": 0.4,
        "spoon_ratio": 0.6,
        "low_sodium": 1,
        "no_added_sugar": 1,
        "updated_at": "2026-03-01T10:00:00",
    }


@pytest.fixture
def mock_inspiration():
    """Minimal inspiration dict for testing."""
    return {
        "id": 1,
        "telegram_user_id": 12345,
        "kind": "text",
        "summary": "Pasta with vegetables",
        "adaptations_json": '["Creamy Veggie Pasta\\nLine 2", "Chicken Rice Bowl\\nLine 2"]',
        "created_at": "2026-03-01T10:00:00",
    }


@pytest.fixture
def mock_plan():
    """Minimal weekly plan dict for testing."""
    return {
        "week_start_date": "2026-03-30",
        "days": {
            "mon": {
                "breakfast": {
                    "title": "Oatmeal",
                    "ingredients": ["oats", "banana"],
                    "quick_prep": "Mix",
                    "safety_note": "Soft",
                    "tags": ["fiber"],
                }
            }
        },
    }


@pytest.fixture
def sample_image_bytes():
    """Return 10KB of valid JPEG-like bytes for testing image handling."""
    # Minimal JPEG header + padding to simulate ~10KB of image data
    # This is a real-ish JPEG magic number followed by null padding
    header = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    padding = b"\x00" * (10 * 1024 - len(header))
    return header + padding
