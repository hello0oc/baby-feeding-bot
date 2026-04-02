# Baby Feeding Bot — Dev Log

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
