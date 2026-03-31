#!/usr/bin/env python3
"""
Gemini Model Connection Test

Tests connectivity and basic response from:
- Primary model (GEMINI_MODEL env, default: gemini-2.5-flash)
- Fallback model (GEMINI_FALLBACK_MODEL env, default: gemini-3.1-flash-lite)

Usage:
    python tests/test_model_connection.py

Environment variables required:
    GEMINI_API_KEY
    GEMINI_MODEL (optional, default: gemini-2.5-flash)
    GEMINI_FALLBACK_MODEL (optional, default: gemini-3.1-flash-lite)
"""
import os
import asyncio
import sys

try:
    import httpx
except ImportError:
    print("httpx not installed. Run: pip install httpx")
    sys.exit(1)

from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("GEMINI_API_KEY")
MODELS_TO_TEST = [
    ("Primary", os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")),
    ("Fallback", os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite")),
]


async def test_model(model_name: str) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": "Say 'Hello, baby feeding bot!' in exactly those words."}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 50},
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=30.0)
            data = resp.json()
            text = ""
            candidates = data.get("candidates") or []
            if candidates:
                parts = (candidates[0].get("content") or {}).get("parts") or []
                if parts:
                    text = parts[0].get("text", "")
            return {
                "model": model_name,
                "status": "PASS" if resp.status_code == 200 and text else "FAIL",
                "http_status": resp.status_code,
                "response_text": text,
                "raw": data,
            }
    except Exception as e:
        return {"model": model_name, "status": "ERROR", "error": str(e)}


async def main():
    print("=" * 50)
    print("  Gemini Model Connection Test")
    print("=" * 50)
    print()

    if not API_KEY:
        print("ERROR: GEMINI_API_KEY environment variable not set.")
        print("Set it with: export GEMINI_API_KEY='your_key'")
        sys.exit(1)

    print(f"API Key: {API_KEY[:8]}...{API_KEY[-4:]}")
    print()

    results = []
    for label, model in MODELS_TO_TEST:
        print(f"Testing {label} ({model})...")
        result = await test_model(model)
        results.append(result)
        status_icon = "OK" if result["status"] == "PASS" else "FAIL"
        print(f"  Status: [{status_icon}] {result['status']}")
        if "response_text" in result:
            print(f"  Response: {result['response_text']}")
        if "error" in result:
            print(f"  Error: {result['error']}")
        print()

    print("=" * 50)
    print("  Summary")
    print("=" * 50)
    for r in results:
        icon = "OK" if r["status"] == "PASS" else "FAIL"
        print(f"  [{icon}] {r['model']}: {r['status']}")

    all_passed = all(r["status"] == "PASS" for r in results)
    print()
    if all_passed:
        print("Result: ALL PASSED - Both models are accessible.")
        return True
    else:
        print("Result: SOME FAILED - Check errors above.")
        return False


if __name__ == "__main__":
    ok = asyncio.get_event_loop().run_until_complete(main())
    sys.exit(0 if ok else 1)