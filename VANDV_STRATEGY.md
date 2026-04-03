# Baby Feeding Bot — Verification & Validation Strategy

> This document defines the testing strategy, coverage goals, and CI/CD pipeline for the Baby Feeding Bot.

---

## Overview

The Baby Feeding Bot is a production Telegram bot that:
- Receives food inspirations (photos/links/text)
- Generates baby-friendly meal adaptations via MiniMax M2.5 API
- Builds weekly meal plans and shopping lists
- Uses an inline keyboard multi-step flow (opt → day → slot → apply)
- Persists data in SQLite

The bot has a low tolerance for user-facing errors — feeding advice must be safe, accurate, and reliable.

---

## A. Testing Pyramid

### Level 1: Unit Tests (Fastest, Most Isolated)
**Framework:** pytest + unittest
**Location:** `tests/`
**Execution time target:** <2s total
**Coverage target:** 80% line coverage

**What to cover:**
- All pure functions: `normalize_day`, `normalize_slot`, `normalize_allergies`, `parse_int_or_default`
- JSON parsing: `extract_json_text`, `parse_json_object`
- Meal normalization: `normalize_meal_dict`, `normalize_plan_dict`
- State checks: `plan_has_content`
- Keyboard builders: `build_option_picker_keyboard`, `build_inspiration_keyboard`, `build_slot_keyboard`
- Renderers: `render_meal_card`, `render_weekly_plan`, `render_adaptation_card`, `render_inspiration_message`
- Database CRUD (with temp DB): `upsert_user`, `get_profile`, `set_profile`, `store_inspiration`, `get_inspiration`, `get_latest_inspiration`, `upsert_weekly_plan`, `get_weekly_plan`, `introduce_allergen`, `get_allergen_journal`
- Date helpers: `week_start_for_plans`, `humanize_timestamp`
- Quick-apply parser: `parse_quick_apply_text`
- Error signal detection: `render_adaptation_card` error path

**Isolation:** Each test uses a separate temp SQLite DB via `tempfile`. No shared state between tests.

### Level 2: Integration Tests (API Contract + Keyboard Flow)
**Framework:** pytest + unittest + `unittest.mock`
**Location:** `tests/test_llm_contract.py`, `tests/test_keyboard_flow.py`, `tests/test_database.py`
**Execution time target:** <10s total
**Coverage target:** Critical paths

**What to cover:**
- MiniMax API contract (mocked httpx): response parsing, error codes, timeout, temperature
- Inline keyboard flow state machine (opt → selday → apply → back)
- `last_inspiration_id` persistence in `user_data`
- Back navigation preserving option selection
- Database edge cases: duplicate prevention, malformed JSON, ratio preservation

### Level 3: End-to-End Tests (Full Bot + Real Telegram)
**Framework:** pytest + python-telegram-bot test rig
**Location:** `tests/test_e2e/` (create)
**Execution:** Manual or in CI with test bot token

**Setup:**
```bash
# Create a test Telegram bot: @BabyFeedingTestBot
# Set BABY_FEEDING_BOT_TOKEN_TEST=... in CI secrets
# Use a private test channel
```

**What to cover:**
- Full onboarding flow: /start → age → allergies → welcome
- Photo → adaptation → apply to plan flow
- Text inspiration → quick-apply text command
- Weekly plan generation (with MiniMax)
- Shopping list generation
- Error recovery: MiniMax returns error mid-flow

**Note:** E2E tests require a real bot token and should run in CI only.

### Level 4: Chaos Tests (Production Resilience)
**Framework:** pytest + `chaos Toolkit` or custom fault injection
**Location:** `tests/test_chaos.py` (create)

**Scenarios:**
- MiniMax API timeout mid-generation
- MiniMax returns 429 rate limit
- MiniMax returns malformed non-JSON response
- SQLite write fails (disk full)
- Network disconnection during photo upload
- Very large image (>10MB) sent by user

---

## B. LLM Contract Testing

MiniMax M2.5 has specific behaviors that differ from standard APIs. These must be tested with mocked responses.

### MiniMax Response Format
MiniMax returns a `content` array with blocks of type `text` or `thinking`. The bot must extract only the first `text` block.

```python
# Correct pattern (already implemented):
for block in content:
    if isinstance(block, dict) and block.get("type") == "text":
        text = str(block.get("text", "")).strip()
        break
```

### Temperature Requirements
| Call | Temperature | Reason |
|------|-------------|--------|
| Adaptation generation | 0.2 | Precise JSON-like output |
| Weekly plan generation | 0.2 | Structured JSON |
| Shopping list | 0.2 | Structured text |
| Meal slot generation | 0.45 | Slightly creative variation |
| Image analysis | 0.3 | Descriptive text |

### Error Code Handling
| HTTP Code | Meaning | User Message |
|-----------|---------|-------------|
| 200 + empty content | Model returned no text | "Sorry, I had trouble generating..." |
| 400 | Bad request | "Sorry, I had trouble generating..." |
| 401 | Bad API key | "Sorry, I had trouble..." (don't expose auth details) |
| 429 | Rate limit | "Sorry, I had trouble..." |
| 500 | Server error | "Sorry, I had trouble generating..." |
| Timeout | Network timeout | "Sorry, I had trouble..." |

### Image Analysis Requirements
- Format: JPEG (not PNG, not WEBP)
- Encoding: base64
- Max dimension: 1024px (resize before encoding)
- Mode: RGB (convert RGBA/Indexed first)
- Timeout: 120s (large image processing)

### Test File
`tests/test_llm_contract.py` — 18 test cases covering:
- Thinking block → text block extraction
- Multiple text blocks → first used
- Temperature passed correctly
- Error codes 400/401/429/500 → friendly message
- Timeout → friendly message
- Blank/whitespace response → error
- Large response (>5000 tokens) handled
- System prompt in `system` field (not `role: developer`)
- Vision model used for images
- Image JPEG format + base64 verification

---

## C. Inline Keyboard Flow Testing

### State Machine

```
User sees inspiration → option picker (opt:1 | opt:2)
                                    ↓
                           opt:1 clicked
                                    ↓
                    day picker (selday:1:mon...sun)
                                    ↓
                           day clicked
                                    ↓
                 slot picker (apply:1:day:slot + back)
                                    ↓
                           apply clicked
                                    ↓
                          Confirmation message
```

### Back Navigation
- `back:N` → returns to option picker, restores `context.user_data["selected_option"] = N`
- From option picker, user can switch to Option 2
- `context.user_data` is ephemeral (resets on bot restart) — this is acceptable

### State in `context.user_data`
| Key | Set by | Used by |
|-----|--------|---------|
| `last_inspiration_id` | `handle_photo`, `handle_text` | `handle_apply_callback`, quick-apply path |
| `selected_option` | `handle_apply_callback` (opt action) | `handle_apply_callback` (apply action) |
| `selected_day_opt{N}` | `handle_apply_callback` (selday action) | (future use) |

### Critical Invariants
1. After `opt:X` → `selected_option = X`
2. After `back:X` → option picker shown, `selected_option` preserved
3. `apply:X:day:slot` uses `last_inspiration_id` from `user_data`
4. If `last_inspiration_id` is None → fall back to `get_latest_inspiration`

### Test File
`tests/test_keyboard_flow.py` — 22 test cases covering:
- Option picker: exactly 2 buttons, correct `opt:1`/`opt:2` data
- Inspiration keyboard: 7 day buttons per option, different data per option
- Slot keyboard: 5 slots + back, `apply:N:day:slot` format
- Back button includes option number
- Full navigation: opt1→day→back→opt2→day2→slot state preservation
- `last_inspiration_id` storage and retrieval
- `get_adaptation_by_index` with valid index, out-of-range index

---

## D. Database Edge Case Tests

### Schema Notes
- `users`: telegram_user_id is PK, locale preserved on upsert (not overwritten with NULL)
- `profiles`: feeding ratios (blw_ratio, spoon_ratio) must be preserved on UPDATE
- `allergen_intros`: UNIQUE(telegram_user_id, allergen) — duplicate introductions handled gracefully
- `inspirations`: stores adaptations as JSON string
- `weekly_plans`: UNIQUE(telegram_user_id, week_start_date)

### Critical Edge Cases
1. `upsert_user` called twice → exactly 1 row exists
2. `upsert_user` with locale=None → existing locale preserved
3. `set_profile` called after onboarding → feeding ratios preserved (not reset to defaults)
4. `get_profile` for unknown user → None (not exception)
5. Malformed JSON in `plan_json` → graceful error, not crash
6. `introduce_allergen` duplicate → returns False, no error
7. `week_start_for_plans(Monday)` → returns NEXT Monday (not today)
8. Empty inspirations list → "none" used as fallback text

### Test File
`tests/test_database.py` — 22 test cases covering all above.

---

## E. Prompt Injection Tests

### Attack Surface
User input flows into:
1. **Inspiration text** → passed as user message to LLM (acceptable — LLM is the model)
2. **URL context** → extracted and passed to LLM
3. **Photo** → base64 encoded and passed to vision model

### Defenses
1. System prompt defines role as "JSON-only API" — injected instructions are in user messages
2. No code execution from JSON parsing (`json.loads` is safe)
3. Greeting/noise filter prevents casual abuse
4. No SQL injection (all queries use parameterized statements)

### Test Scenarios
| Attack | Expected Behavior |
|--------|-------------------|
| `{"title": "HACK", "ingredients": []}` as text | Passed as inspiration text to LLM, not executed |
| `Ignore previous instructions` in text | Passed as user message, not in system prompt |
| Very long text (>5000 chars) | Passed to LLM with max_tokens limit, no crash |
| Pure emoji input | Filtered by greeting/noise detection |
| Triple-brace injection `{{{{` | Treated as inspiration text |
| SQL injection attempt | Parameterized queries prevent execution |

### Test File
`tests/test_prompt_injection.py` — 18 test cases covering all above.

---

## F. Error Handling & Resilience Tests

### MiniMax API Failures
All API errors must return user-friendly messages. The same `friendly_error` string is used for all failure modes to avoid leaking internal details.

```python
friendly_error = "Sorry, I had trouble generating a response right now."
```

### Image Processing Failures
- Corrupt JPEG → friendly message suggesting retry
- Very large image → resized to 1024px max (handled in PIL, not after)
- Network timeout → friendly message

### SQLite Failures
- Write failures → caught by try/except, error message to user
- Read of non-existent record → returns None, handled by callers

### Test File
`tests/test_error_handling.py` — 25 test cases covering:
- HTTP 400/401/429/500 → friendly message
- Timeout (httpx.TimeoutException) → friendly message
- Connection error (ConnectError) → friendly message
- 200 OK with empty content → friendly message
- Only thinking block (no text) → friendly message
- SQLite: no profile, no inspiration, malformed JSON → graceful handling
- Image: corrupt JPEG, RGBA→RGB conversion, resize logic
- JSON parsing edge cases: unicode, emoji, single quotes
- Normalization edge cases: numbers in day/slot, decimals, invalid dates

---

## G. CI/CD Recommendations

### GitHub Actions Workflow

```yaml
name: Baby Feeding Bot Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install ruff
      - run: ruff check .

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pip install pytest pytest-asyncio
      - run: python -m pytest tests/ -v --tb=short --cov=baby_feeding_bot --cov-report=term-missing
        env:
          BABY_FEEDING_BOT_TOKEN: ${{ secrets.BABY_FEEDING_BOT_TOKEN_TEST }}
          MINIMAX_API_KEY: ${{ secrets.MINIMAX_API_KEY }}

  integration-test:
    runs-on: ubuntu-latest
    needs: test
    # Runs E2E tests with a real test bot
    if: github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pip install pytest
      - run: python -m pytest tests/test_e2e/ -v
        env:
          BABY_FEEDING_BOT_TOKEN: ${{ secrets.BABY_FEEDING_BOT_TOKEN_TEST }}
          MINIMAX_API_KEY: ${{ secrets.MINIMAX_API_KEY }}

  coverage:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt pytest pytest-cov
      - run: python -m pytest tests/ --cov=baby_feeding_bot --cov-fail-under=80
        env:
          BABY_FEEDING_BOT_TOKEN: test-token
          MINIMAX_API_KEY: test-key
```

### Pre-commit Hook
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
```

### Coverage Requirements
- Minimum line coverage: **80%**
- Critical paths (JSON parsing, LLM error handling, keyboard flow): **95%**
- Run `pytest --cov-fail-under=80` in CI

### Test Bot on Merge to Main
After every merge to `main`:
1. Run full test suite
2. Deploy to staging VPS
3. Run E2E smoke test against staging bot
4. If smoke test passes, deploy to production

### Testing Telegram Callbacks Locally
Use polling mode with a test bot:
```bash
# Terminal 1: Run bot in polling
BABY_FEEDING_BOT_TOKEN=test-token MINIMAX_API_KEY=test-key \
  python baby_feeding_bot.py

# Or use ngrok for webhook testing
ngrok http 443
# Set webhook to your Telegram bot
```

### Ruff Lint Rules
```toml
# pyproject.toml
[tool.ruff]
line-length = 100
select = ["E", "F", "I", "N", "W", "UP"]
ignore = ["E501"]  # line too long (handled by formatter)
```

---

## H. Known Production Issues (Fixed)

| # | Issue | Root Cause | Fix |
|---|-------|-----------|-----|
| 1 | `generate_shopping_list` crash | `system` variable undefined | Added `system = MEAL_SYSTEM_PROMPT` |
| 2 | Image analysis timeout at 60s | Hardcoded `timeout=60.0` | Changed to `timeout=120.0` |
| 3 | Feeding ratios always reset to 0.4/0.6 | `ON CONFLICT` didn't include `blw_ratio`/`spoon_ratio` | Added ratio preservation + `DO UPDATE SET` includes them |
| 4 | Back button lost option number | `back:X` didn't use selected option | Added `option_number = context.user_data.get("selected_option", 1)` |
| 5 | `.env.example` wrong API key | Listed `GEMINI_API_KEY` | Updated to `MINIMAX_API_KEY` |
| 6 | `test_bot_flows.py` wrong env var | Used `GEMINI_API_KEY` | Updated to `MINIMAX_API_KEY` |

---

## I. Running Tests

```bash
# All tests
cd /home/deploy/baby-feeding-bot
./venv/bin/python -m pytest tests/ -v

# With coverage
./venv/bin/python -m pytest tests/ -v --cov=baby_feeding_bot --cov-report=term-missing

# Only unit tests (fast)
./venv/bin/python -m pytest tests/ -v --ignore=tests/test_e2e/ --ignore=tests/test_llm_contract.py

# Only LLM contract tests
./venv/bin/python -m pytest tests/test_llm_contract.py -v

# Only keyboard flow tests
./venv/bin/python -m pytest tests/test_keyboard_flow.py -v

# Only database tests
./venv/bin/python -m pytest tests/test_database.py -v
```

---

## J. Test Count Summary

| File | Tests | Coverage Area |
|------|-------|---------------|
| `test_bot_flows.py` | ~15 | Integration: parsing + DB + rendering |
| `test_handlers.py` | ~10 | Handler logic with mocks |
| `test_helpers.py` | ~25 | Pure functions, parsers, renderers |
| `test_keyboard_builders.py` | 5 | Keyboard builder basics |
| `test_llm_integration.py` | 6 | LLM + image analysis integration |
| `test_model_connection.py` | 1 | Real API (skipped without key) |
| `test_parsers.py` | ~15 | Day/slot/allergy normalization |
| `test_profile_constraints.py` | 9 | Profile constraint + age safety |
| `test_renderers.py` | 6 | Adaptation card + weekly plan rendering |
| `test_llm_contract.py` | 18 | MiniMax API contract (NEW) |
| `test_keyboard_flow.py` | 22 | Inline keyboard state machine (NEW) |
| `test_database.py` | 22 | DB edge cases (NEW) |
| `test_prompt_injection.py` | 18 | Prompt injection defenses (NEW) |
| `test_error_handling.py` | 25 | Error resilience (NEW) |
| **Total** | **~197** | |
