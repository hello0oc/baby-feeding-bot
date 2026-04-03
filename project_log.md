# Baby Feeding Bot — Dev Log

## 2026-04-02 — Deep Code Review + V&V + Bug Fixes

### Bugs Found & Fixed

#### P0: `generate_shopping_list` NameError (CRASH)
- **Bug:** Used undefined `system` variable → `NameError: name 'system' is not defined`
- **Fix:** Added `system = MEAL_SYSTEM_PROMPT` with Spanish language detection

#### P0: `analyze_image_for_inspiration` timeout too short
- **Bug:** Hardcoded `timeout=60.0` — image processing can take longer
- **Fix:** Changed to `timeout=120.0` (matching main LLM calls)

#### P0: `set_profile` always resets feeding ratios to defaults
- **Bug:** `ON CONFLICT DO UPDATE` omitted `blw_ratio` and `spoon_ratio` columns, so updating age/allergies always reset ratios to 0.4/0.6
- **Fix:** Added `blw_ratio`/`spoon_ratio` to INSERT and UPDATE SET clause; added SELECT to preserve existing values when not explicitly provided

#### P1: `back:X` callback loses selected option number
- **Bug:** `back:X` returned to option picker but didn't restore `selected_option` in `context.user_data`, causing subsequent navigation to use wrong option
- **Fix:** Added `option_number = context.user_data.get("selected_option", 1)` before showing option picker

#### P1: `plan_has_content` checked dict truthiness, not meal validity
- **Bug:** `any(plan["days"].values())` returned True for day-slots dicts containing only invalid meals (no title) — empty slot dicts are truthy in Python
- **Fix:** Rewrote to explicitly check `meal.get("title")` — only valid meals count as content

#### P2: `.env.example` listed wrong API key variable
- **Bug:** Listed `GEMINI_API_KEY` instead of `MINIMAX_API_KEY`
- **Fix:** Updated to `MINIMAX_API_KEY`

#### P2: Test files used wrong env var name
- **Bug:** `test_bot_flows.py` and `test_helpers.py` used `GEMINI_API_KEY` instead of `MINIMAX_API_KEY`
- **Fix:** Updated both to `MINIMAX_API_KEY`

### New Test Files Added
- `tests/test_llm_contract.py` — 18 tests: MiniMax API contract (thinking blocks, temperature, error codes, system prompt, image analysis)
- `tests/test_keyboard_flow.py` — 22 tests: Inline keyboard state machine (opt→selday→apply→back, state preservation)
- `tests/test_database.py` — 22 tests: DB edge cases (upsert, ratio preservation, plan normalization, allergen intros, week start)
- `tests/test_prompt_injection.py` — 19 tests: Prompt injection defenses (JSON injection, system prompt leakage, greeting filter)
- `tests/test_error_handling.py` — 25 tests: Error resilience (all HTTP codes, SQLite errors, image corruption)

### New Files
- `VANDV_STRATEGY.md` — Comprehensive V&V strategy (testing pyramid, LLM contract, keyboard flow, CI/CD, coverage targets)
- `scripts/restart_bot.sh` — Safe bot restart script (graceful stop, nohup start, PID file, health check)

### Bug: `normalize_plan_dict` Was NOT Mutating Input
- Initial investigation suggested `normalize_plan_dict` mutated its input — FALSE ALARM. It creates a new `normalized_days` dict. The real bug was in `plan_has_content` (above).

### Test Results
- Before: 62 passed, 1 skipped (test_bot_flows.py broken)
- After: 222 passed, 1 skipped (all passing)

### Code Review Findings (No Fix Needed)
- MiniMax thinking blocks: `extract_json_text` correctly handles `type: "text"` blocks (thinking blocks are `type: "thinking"` and skipped)
- Temperature settings: adaptation = 0.2, weekly plan = 0.2, meal slot = 0.45 ✓
- Inline keyboard Option 2: Both buttons have `opt:2` callback data ✓
- "No weekly plan" error: Shows visible text message, not just toast ✓
- `profile_constraints_text`: Uses `profile.get("age_months", 12)` ✓
- BLW/spoon ratio: Injected into prompts via `profile_constraints_text()` ✓
- SQLite: All queries use parameterized `?` placeholders — safe from injection ✓

### CI/CD Recommendations (in VANDV_STRATEGY.md)
- Ruff linting with pre-commit hook
- GitHub Actions: lint → test → integration-test → coverage gate
- Minimum 80% line coverage
- E2E smoke tests on merge to main
- Test bot polling for local callback testing

---

## 2026-04-02 — MiniMax Switch + P0-P2 Features

## 2026-04-02 — MiniMax Switch + P0-P2 Features

### SWITCH LLM: Gemini → MiniMax ✅
- Removed all Gemini API code (`gemini_generate`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`)
- Replaced with `llm_generate()` using MiniMax M2.5 via Anthropic Messages API endpoint (`https://api.minimaxi.com/anthropic/v1/messages`)
- Auth: `Authorization: Bearer <api_key>` header
- Model: `MiniMax-M2.5` with `thinking: {type: "disabled"}` for speed
- System prompt goes in `role: "developer"` (or appended to prompt as `system_prompt=`)
- Image analysis uses native MiniMax image blocks in the user message content array
- Error handling: same fallback-friendly pattern
- API key: reads `MINIMAX_API_KEY` env var (same pattern as old `GEMINI_API_KEY`)

### P0: Fix profile_constraints_text() ✅
- Changed `"Baby age: 12 months"` to `profile.get('age_months', 12)`

### P0: Age-specific meal texture/safety rules ✅
- Added `age_safety_rules_text(profile: dict) -> str`
- 6 age brackets: 4-6, 6-9, 9-12, 12-18, 18-24, 24+ months
- Each includes stage description + choking hazard warning
- Injected into ALL prompts calling `llm_generate()`:
  - `generate_two_adaptations()`
  - `generate_weekly_plan()`
  - `generate_meal_for_slot()`

### P1: Interactive slot picker (tap-to-apply) ✅
- `render_inspiration_message()` now returns `tuple[str, InlineKeyboardMarkup]`
- Added `build_inspiration_keyboard(option_number)` → day picker (Mon/Wed/Fri | Tue/Thu/Sat/Sun)
- Added `build_slot_keyboard(option_number, day_key)` → slot buttons (Breakfast/Snack1/Lunch/Snack2/Dinner)
- Added `handle_apply_callback()` → handles `selday:`, `apply:`, `back:` callbacks
- Text fallback "Use 1 for Wednesday dinner" preserved for backwards compat
- Callback data format: `apply:option:day:slot` (e.g. `apply:1:wed:dinner`)
- Registered `CallbackQueryHandler` with pattern `^(selday|apply|back):` before generic text handler

### P1: Allergen intro tracker ✅
- Added `allergen_intros` table with `UNIQUE(telegram_user_id, allergen)` constraint
- Added `introduced_allergens TEXT NOT NULL DEFAULT ''` to `profiles` table (safe ALTER, won't break existing data)
- Added DB functions: `get_introduced_allergens()`, `introduce_allergen()`, `get_allergen_journal()`
- Added `ALLERGEN_TRACK_LIST = ["milk", "egg", "peanut", "tree nuts", "soy", "wheat", "fish", "shellfish", "sesame"]`
- New menu item "🥜 Allergen journal" → `allergen_journal_command()`
- `/introduce <allergen> [reactions]` → `introduce_command()` with validation against track list
- First introduction tip: "serve a small amount and wait 3-4 days"
- Allergen intro note injected into meal plan/adaptation prompts (first intro detection)

### P1: Feedback → meal plan improvement loop ✅
- Added `get_meal_rating_stats(telegram_user_id, week_start)` → returns avg per slot, per tag, total count
- Added `get_negatively_rated_meal_ids()` → returns meal IDs with >50% negative ratings
- `generate_weekly_plan()` injects "Based on past feedback, user prefers: ..." when N >= 3
- Post-plan message: "You've rated N meals — shall I factor your preferences into next week's plan?" (shown when N >= 3)
- `generate_shopping_list()` filters out negatively rated meals

### P2: Free-text greeting filter ✅
- Added to top of `handle_text()`:
  - Greeting patterns: `^(hi|hello|hey|hola|good morning|good evening|buenos días|qué tal|howdy)$`, `^start$`
  - Pure emoji/single character noise filter
- Shows friendly welcome message with main menu markup

### P2: BLW/spoon ratio → prompt injection ✅
- `profile_constraints_text()` already includes BLW/spoon ratio — confirmed working
- This was already being passed to prompts

### P2: /regenerate command ✅
- Added `regenerate_command()` → `/regenerate <day> <slot>` e.g. `/regenerate wed lunch`
- Shows new meal with Accept/Revert inline buttons
- Added `handle_regen_callback()` → handles `regen_accept:` and `regen_revert:` callbacks
- Registered both `CommandHandler("regenerate", ...)` and `CallbackQueryHandler(handle_regen_callback, pattern=r"^regen_")`

### Tests
- 45/45 tests pass (pytest)
- 3 test failures fixed (return type change for `render_inspiration_message`, env var name, async test naming)
- Bot starts without import/syntax errors (only expected "Invalid token" error from dummy test token)
- Warnings: `datetime.utcnow()` deprecation (non-breaking)

### Files Modified
- `baby_feeding_bot.py` — all changes
- `requirements.txt` — added `anthropic>=0.40.0`
- `README.md` — updated for MiniMax switch, new features, updated command reference
- `tests/test_bot_flows.py` — updated for tuple return type + env var name
- `tests/test_helpers.py` — updated for tuple return type + env var name
- `tests/test_model_connection.py` — rewritten for MiniMax API
- `project_log.md` — this file (new)
