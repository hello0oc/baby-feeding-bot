#!/usr/bin/env python3
"""
MiniMax Model Connection Test

Tests connectivity and basic response from MiniMax-M2.5.
Skips when MINIMAX_API_KEY is a placeholder or test value.

Usage:
    python tests/test_model_connection.py
"""
import os
import asyncio
import sys

MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
SKIP_KEYS = {"", "test", "test-key", "your_key_here", "placeholder", "sk-cp-test"}


async def _test_model_impl() -> dict:
    """Test that MiniMax API is reachable with a real key."""
    import httpx

    url = "https://api.minimaxi.com/anthropic/v1/messages"
    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": "MiniMax-M2.5",
        "messages": [{"role": "user", "content": "Say 'Hello, baby feeding bot!' in exactly those words."}],
        "max_tokens": 50,
        "temperature": 0.1,
        "thinking": {"type": "disabled"},
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload, timeout=30.0)
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    text = str(data.get("content", [{}])[0].get("text", "")).strip()
    assert "Hello, baby feeding bot!" in text, f"Unexpected response: {text}"
    return {"status": "OK", "text": text}


def test_model_connection():
    """Sync wrapper for pytest — skips on placeholder keys."""
    if MINIMAX_API_KEY in SKIP_KEYS:
        import pytest
        pytest.skip("Requires real MINIMAX_API_KEY")
    result = asyncio.run(_test_model_impl())
    assert result["status"] == "OK"


if __name__ == "__main__":
    if MINIMAX_API_KEY in SKIP_KEYS:
        print("SKIP: Set a real MINIMAX_API_KEY to run this test")
        sys.exit(0)
    result = asyncio.run(_test_model_impl())
    print(f"OK: {result}")
