#!/usr/bin/env python3
"""
Baby Feeding Bot - Micro MVP
Receives inspirations (photos/links/text), generates baby-safe adaptations, and builds weekly meal plans.
"""

import os
import logging
import base64
import json
import re
import sqlite3
import hashlib
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from PIL import Image

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
load_dotenv()
TELEGRAM_BOT_TOKEN = os.environ.get("BABY_FEEDING_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_PLACES_API_KEY")
DB_PATH = os.environ.get("BABY_FEEDING_DB_PATH", "baby_feeding.sqlite3")
RETENTION_INSPIRATIONS_DAYS = int(os.environ.get("BABY_FEEDING_RETENTION_INSPIRATIONS_DAYS", "90"))
RETENTION_FEEDBACK_DAYS = int(os.environ.get("BABY_FEEDING_RETENTION_FEEDBACK_DAYS", "90"))
RETENTION_PLANS_DAYS = int(os.environ.get("BABY_FEEDING_RETENTION_PLANS_DAYS", "365"))

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("BABY_FEEDING_BOT_TOKEN environment variable not set")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set (also accepts GOOGLE_PLACES_API_KEY)")

# System prompt for meal generation
MEAL_SYSTEM_PROMPT = """You are a helpful assistant that creates baby-friendly meals for a 12-month-old child.

You must follow parental constraints and baby-safety guidelines.

Guidelines for baby meals:
- Age-appropriate textures (soft, easy to chew/gum)
- Nutritious ingredients
- Simple preparation
- Avoid: honey, choking hazards (whole nuts, whole grapes), excess salt, added sugar, raw/undercooked foods

Respond in a friendly, concise format:
- Keep it practical and encouraging"""

ONBOARDING_AGE, ONBOARDING_ALLERGIES = range(2)


def _db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _db_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_user_id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL,
                locale TEXT,
                preferred_language TEXT,
                onboarding_completed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                telegram_user_id INTEGER PRIMARY KEY,
                age_months INTEGER NOT NULL,
                allergies TEXT NOT NULL,
                low_sodium INTEGER NOT NULL DEFAULT 1,
                no_added_sugar INTEGER NOT NULL DEFAULT 1,
                blw_ratio REAL NOT NULL DEFAULT 0.4,
                spoon_ratio REAL NOT NULL DEFAULT 0.6,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inspirations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                source_url TEXT,
                image_sha256 TEXT,
                summary TEXT NOT NULL,
                adaptations_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weekly_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                week_start_date TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(telegram_user_id, week_start_date),
                FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                weekly_plan_id INTEGER NOT NULL,
                meal_id TEXT NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id),
                FOREIGN KEY (weekly_plan_id) REFERENCES weekly_plans(id)
            )
            """
        )


def cleanup_retention() -> None:
    now = datetime.utcnow()
    inspirations_cutoff = (now - timedelta(days=RETENTION_INSPIRATIONS_DAYS)).isoformat()
    feedback_cutoff = (now - timedelta(days=RETENTION_FEEDBACK_DAYS)).isoformat()
    plans_cutoff_date = (now.date() - timedelta(days=RETENTION_PLANS_DAYS)).isoformat()
    with _db_conn() as conn:
        conn.execute("DELETE FROM inspirations WHERE created_at < ?", (inspirations_cutoff,))
        conn.execute("DELETE FROM feedback WHERE created_at < ?", (feedback_cutoff,))
        conn.execute("DELETE FROM weekly_plans WHERE week_start_date < ?", (plans_cutoff_date,))


def upsert_user(telegram_user_id: int, locale: Optional[str]) -> None:
    now = datetime.utcnow().isoformat()
    with _db_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (telegram_user_id, created_at, locale, preferred_language, onboarding_completed)
            VALUES (?, ?, ?, NULL, 0)
            ON CONFLICT(telegram_user_id) DO UPDATE SET locale = COALESCE(excluded.locale, users.locale)
            """,
            (telegram_user_id, now, locale),
        )


def get_profile(telegram_user_id: int) -> Optional[dict[str, Any]]:
    with _db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM profiles WHERE telegram_user_id = ?",
            (telegram_user_id,),
        ).fetchone()
        return dict(row) if row else None


def set_profile(
    telegram_user_id: int,
    *,
    age_months: int,
    allergies: str,
    preferred_language: Optional[str] = None,
) -> None:
    now = datetime.utcnow().isoformat()
    with _db_conn() as conn:
        conn.execute(
            """
            INSERT INTO profiles (
                telegram_user_id, age_months, allergies,
                low_sodium, no_added_sugar, blw_ratio, spoon_ratio,
                updated_at
            )
            VALUES (?, ?, ?, 1, 1, 0.4, 0.6, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                age_months = excluded.age_months,
                allergies = excluded.allergies,
                updated_at = excluded.updated_at
            """,
            (telegram_user_id, age_months, allergies, now),
        )
        conn.execute(
            """
            UPDATE users
            SET onboarding_completed = 1,
                preferred_language = COALESCE(?, preferred_language)
            WHERE telegram_user_id = ?
            """,
            (preferred_language, telegram_user_id),
        )


def get_user_language(telegram_user_id: int, fallback: str) -> str:
    with _db_conn() as conn:
        row = conn.execute(
            "SELECT preferred_language FROM users WHERE telegram_user_id = ?",
            (telegram_user_id,),
        ).fetchone()
        if row and row["preferred_language"]:
            return str(row["preferred_language"])
    return fallback


def next_monday(d: date) -> date:
    days_ahead = (7 - d.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return d + timedelta(days=days_ahead)


def week_start_for_plans(today: date) -> date:
    return next_monday(today)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


async def gemini_generate(parts: list[dict[str, Any]], *, temperature: float = 0.4, max_tokens: int = 2048) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    async with httpx.AsyncClient() as http_client:
        response = await http_client.post(url, json=payload, timeout=45.0)
        if response.status_code != 200:
            logger.error("Gemini API error: %s", response.status_code)
            return "Sorry, I had trouble generating a response right now."
        result = response.json()
        candidates = result.get("candidates") or []
        if not candidates:
            return "Sorry, I couldn't generate a response."
        content = (candidates[0].get("content") or {}).get("parts") or []
        if not content:
            return "Sorry, I couldn't generate a response."
        return str(content[0].get("text") or "").strip() or "Sorry, I couldn't generate a response."


def parse_int_or_default(text: str, default: int) -> int:
    text = (text or "").strip()
    if not text:
        return default
    m = re.search(r"\d+", text)
    if not m:
        return default
    value = int(m.group(0))
    if value < 4:
        return 4
    if value > 36:
        return 36
    return value


def normalize_allergies(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return "none"
    if cleaned.lower() in {"none", "no", "nope", "n/a"}:
        return "none"
    items = [x.strip() for x in re.split(r"[,;\n]+", cleaned) if x.strip()]
    return ", ".join(items) if items else "none"


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send help message when /help is issued."""
    if not update.message:
        return
    await update.message.reply_text(
        "Send me:\n"
        "- a screenshot/photo of food, or\n"
        "- a link, or\n"
        "- a text prompt.\n\n"
        "I’ll propose 2 baby-safe adaptations and you can apply them into next week’s plan.\n\n"
        "Key commands:\n"
        "/weekly_plan, /shopping_list, /history, /apply, /rate"
    )


async def analyze_image_for_inspiration(image_bytes: bytes, *, language: str) -> str:
    try:
        img = Image.open(BytesIO(image_bytes))
        max_dim = 1024
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buffered = BytesIO()
        img.save(buffered, format="JPEG", quality=85)
        img_str = base64.b64encode(buffered.getvalue()).decode()
        prompt = (
            "Describe the food shown and extract a short theme I can use as a meal inspiration.\n"
            "Return 2-3 bullet points.\n"
            f"Respond in language: {language}"
        )
        return await gemini_generate(
            [
                {"text": prompt},
                {"inlineData": {"mimeType": "image/jpeg", "data": img_str}},
            ],
            temperature=0.3,
            max_tokens=512,
        )
    except Exception as e:
        logger.error("Error analyzing image: %s", e)
        return "Sorry, I had trouble analyzing that image."


def profile_constraints_text(profile: Optional[dict[str, Any]]) -> str:
    if not profile:
        return (
            "Baby age: 12 months\n"
            "Allergies: none\n"
            "Dietary rules: low sodium; no added sugar\n"
            "Feeding style: 40% BLW, 60% spoon-fed"
        )
    return (
        f"Baby age: {profile.get('age_months', 12)} months\n"
        f"Allergies: {profile.get('allergies', 'none')}\n"
        "Dietary rules: low sodium; no added sugar\n"
        f"Feeding style: {int(float(profile.get('blw_ratio', 0.4)) * 100)}% BLW, "
        f"{int(float(profile.get('spoon_ratio', 0.6)) * 100)}% spoon-fed"
    )


async def generate_two_adaptations(*, inspiration: str, profile: Optional[dict[str, Any]], language: str) -> list[str]:
    prompt = (
        f"{MEAL_SYSTEM_PROMPT}\n\n"
        "Task: Based on the inspiration, propose exactly 2 baby-safe meal adaptations.\n"
        "Each adaptation must be 3-5 lines:\n"
        "- Meal name\n"
        "- Key ingredients\n"
        "- Quick prep\n"
        "- Safety note\n\n"
        f"Constraints:\n{profile_constraints_text(profile)}\n\n"
        f"Inspiration:\n{inspiration}\n\n"
        f"Respond in language: {language}"
    )
    text = await gemini_generate([{"text": prompt}], temperature=0.4, max_tokens=700)
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) >= 2:
        return [blocks[0], blocks[1]]
    return [text.strip(), ""]


def store_inspiration(
    telegram_user_id: int,
    *,
    kind: str,
    summary: str,
    adaptations: list[str],
    source_url: Optional[str] = None,
    image_sha: Optional[str] = None,
) -> int:
    now = datetime.utcnow().isoformat()
    with _db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO inspirations (telegram_user_id, kind, source_url, image_sha256, summary, adaptations_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (telegram_user_id, kind, source_url, image_sha, summary, json.dumps(adaptations, ensure_ascii=False), now),
        )
        return int(cur.lastrowid)


def get_inspiration(telegram_user_id: int, inspiration_id: int) -> Optional[dict[str, Any]]:
    with _db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM inspirations WHERE id = ? AND telegram_user_id = ?",
            (inspiration_id, telegram_user_id),
        ).fetchone()
        return dict(row) if row else None


def get_recent_inspirations(telegram_user_id: int, limit: int = 5) -> list[dict[str, Any]]:
    with _db_conn() as conn:
        rows = conn.execute(
            "SELECT id, kind, source_url, created_at, summary FROM inspirations WHERE telegram_user_id = ? ORDER BY id DESC LIMIT ?",
            (telegram_user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_weekly_plan(telegram_user_id: int, *, week_start: date, plan_json: str) -> int:
    now = datetime.utcnow().isoformat()
    with _db_conn() as conn:
        conn.execute(
            """
            INSERT INTO weekly_plans (telegram_user_id, week_start_date, plan_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id, week_start_date) DO UPDATE SET
                plan_json = excluded.plan_json,
                updated_at = excluded.updated_at
            """,
            (telegram_user_id, week_start.isoformat(), plan_json, now, now),
        )
        row = conn.execute(
            "SELECT id FROM weekly_plans WHERE telegram_user_id = ? AND week_start_date = ?",
            (telegram_user_id, week_start.isoformat()),
        ).fetchone()
        return int(row["id"]) if row else 0


def get_weekly_plan(telegram_user_id: int, *, week_start: date) -> Optional[dict[str, Any]]:
    with _db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM weekly_plans WHERE telegram_user_id = ? AND week_start_date = ?",
            (telegram_user_id, week_start.isoformat()),
        ).fetchone()
        return dict(row) if row else None


def get_recent_plans(telegram_user_id: int, limit: int = 3) -> list[dict[str, Any]]:
    with _db_conn() as conn:
        rows = conn.execute(
            "SELECT id, week_start_date, created_at, updated_at FROM weekly_plans WHERE telegram_user_id = ? ORDER BY week_start_date DESC LIMIT ?",
            (telegram_user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def render_weekly_plan(plan: dict[str, Any]) -> str:
    days = plan.get("days") or {}
    order_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    slot_order = ["breakfast", "snack1", "lunch", "snack2", "dinner"]
    slot_labels = {
        "breakfast": "Breakfast",
        "snack1": "Snack 1",
        "lunch": "Lunch",
        "snack2": "Snack 2",
        "dinner": "Dinner",
    }
    lines: list[str] = []
    for d in order_days:
        day = days.get(d)
        if not isinstance(day, dict):
            continue
        lines.append(d.upper())
        for slot in slot_order:
            meal = day.get(slot)
            if not isinstance(meal, dict):
                continue
            title = str(meal.get("title") or "Meal")
            tags = meal.get("tags") or []
            tags_text = f" ({', '.join(tags)})" if isinstance(tags, list) and tags else ""
            lines.append(f"- {slot_labels[slot]} [{d}.{slot}]: {title}{tags_text}")
        lines.append("")
    return "\n".join(lines).strip()


async def generate_weekly_plan(
    *,
    profile: Optional[dict[str, Any]],
    inspirations: list[dict[str, Any]],
    week_start: date,
    language: str,
) -> dict[str, Any]:
    inspiration_text = "\n".join([f"- {i.get('summary', '')}".strip() for i in inspirations if i.get("summary")]) or "none"
    prompt = (
        f"{MEAL_SYSTEM_PROMPT}\n\n"
        "Create a weekly meal plan for a 12-month-old.\n"
        "Structure requirements:\n"
        "- 7 days: mon..sun\n"
        "- 5 slots/day: breakfast, snack1, lunch, snack2, dinner\n"
        "For each slot, return an object with:\n"
        "- title (string)\n"
        "- ingredients (array of strings)\n"
        "- quick_prep (string)\n"
        "- safety_note (string)\n"
        "- tags (array of strings; e.g., iron-rich, calcium, protein, fiber)\n\n"
        f"Constraints:\n{profile_constraints_text(profile)}\n\n"
        f"Week starts: {week_start.isoformat()}\n"
        f"Inspirations (themes):\n{inspiration_text}\n\n"
        "Return ONLY valid JSON matching this top-level shape:\n"
        '{ "week_start_date": "YYYY-MM-DD", "days": { "mon": { "breakfast": {...}, "snack1": {...}, "lunch": {...}, "snack2": {...}, "dinner": {...} }, "...": "..." } }\n\n'
        f"Respond in language: {language}"
    )
    text = await gemini_generate([{"text": prompt}], temperature=0.5, max_tokens=2500)
    try:
        return json.loads(text)
    except Exception:
        return {"week_start_date": week_start.isoformat(), "days": {}, "raw": text}


async def generate_shopping_list(*, plan_json: dict[str, Any], language: str) -> str:
    prompt = (
        "Create a consolidated shopping list grouped by category (produce, protein, dairy, pantry, other).\n"
        "Avoid adding salt/sugar items. Keep it concise.\n\n"
        f"Plan JSON:\n{json.dumps(plan_json, ensure_ascii=False)}\n\n"
        f"Respond in language: {language}"
    )
    return await gemini_generate([{"text": prompt}], temperature=0.2, max_tokens=1200)


async def generate_meal_for_slot(
    *,
    profile: Optional[dict[str, Any]],
    inspiration_summary: str,
    day_key: str,
    slot_key: str,
    language: str,
) -> dict[str, Any]:
    prompt = (
        f"{MEAL_SYSTEM_PROMPT}\n\n"
        "Create a single meal for the specified day+slot, inspired by the inspiration.\n"
        "Return ONLY valid JSON with keys: title, ingredients (array), quick_prep, safety_note, tags (array).\n\n"
        f"Constraints:\n{profile_constraints_text(profile)}\n\n"
        f"Day: {day_key}\nSlot: {slot_key}\n"
        f"Inspiration:\n{inspiration_summary}\n\n"
        f"Respond in language: {language}"
    )
    text = await gemini_generate([{"text": prompt}], temperature=0.45, max_tokens=900)
    try:
        return json.loads(text)
    except Exception:
        return {"title": "Meal", "ingredients": [], "quick_prep": text, "safety_note": "", "tags": []}


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming photos."""
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    await update.message.chat.send_action("typing")
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = bytes(await file.download_as_bytearray())
        language = get_user_language(user.id, user.language_code or "en")
        inspiration_summary = await analyze_image_for_inspiration(image_bytes, language=language)
        profile = get_profile(user.id)
        adaptations = await generate_two_adaptations(
            inspiration=inspiration_summary,
            profile=profile,
            language=language,
        )
        inspiration_id = store_inspiration(
            user.id,
            kind="photo",
            summary=inspiration_summary,
            adaptations=adaptations,
            image_sha=sha256_hex(image_bytes),
        )
        await update.message.reply_text(
            f"Inspiration saved (id: {inspiration_id}). Here are 2 baby-safe adaptations:\n\n"
            f"1)\n{adaptations[0]}\n\n"
            f"2)\n{adaptations[1]}\n\n"
            "Apply into next week’s plan:\n"
            "/apply <id> <day> <slot>\n"
            "Example:\n"
            f"/apply {inspiration_id} mon dinner"
        )
    except Exception as e:
        logger.error("Error handling photo: %s", e)
        await update.message.reply_text("Sorry, something went wrong processing your image.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages."""
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    language = get_user_language(user.id, user.language_code or "en")
    text = (update.message.text or "").strip()
    if not text:
        return
    urls = URL_RE.findall(text)
    profile = get_profile(user.id)
    await update.message.chat.send_action("typing")
    if urls:
        url = urls[0]
        summary_prompt = (
            "Extract a short theme from this link context suitable as a meal inspiration.\n"
            "Return 2-3 bullet points.\n\n"
            f"Link: {url}\n"
            f"Message context: {text}\n\n"
            f"Respond in language: {language}"
        )
        inspiration_summary = await gemini_generate([{"text": summary_prompt}], temperature=0.3, max_tokens=400)
        adaptations = await generate_two_adaptations(inspiration=inspiration_summary, profile=profile, language=language)
        inspiration_id = store_inspiration(
            user.id,
            kind="link",
            source_url=url,
            summary=inspiration_summary,
            adaptations=adaptations,
        )
        await update.message.reply_text(
            f"Inspiration saved (id: {inspiration_id}). Here are 2 baby-safe adaptations:\n\n"
            f"1)\n{adaptations[0]}\n\n"
            f"2)\n{adaptations[1]}\n\n"
            "Apply into next week’s plan:\n"
            "/apply <id> <day> <slot>\n"
            "Example:\n"
            f"/apply {inspiration_id} tue lunch"
        )
        return
    inspiration_summary = text
    adaptations = await generate_two_adaptations(inspiration=inspiration_summary, profile=profile, language=language)
    inspiration_id = store_inspiration(
        user.id,
        kind="text",
        summary=inspiration_summary,
        adaptations=adaptations,
    )
    await update.message.reply_text(
        f"Inspiration saved (id: {inspiration_id}). Here are 2 baby-safe adaptations:\n\n"
        f"1)\n{adaptations[0]}\n\n"
        f"2)\n{adaptations[1]}\n\n"
        "Apply into next week’s plan:\n"
        "/apply <id> <day> <slot>\n"
        "Example:\n"
        f"/apply {inspiration_id} wed breakfast"
    )


async def onboarding_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return ConversationHandler.END
    user = update.effective_user
    if not user:
        return ConversationHandler.END
    upsert_user(user.id, user.language_code)
    profile = get_profile(user.id)
    if profile:
        await update.message.reply_text(
            "You’re set up.\n\n"
            "Commands:\n"
            "/weekly_plan - generate or show next week’s plan\n"
            "/shopping_list - shopping list for next week\n"
            "/history - recent plans and inspirations\n"
            "/set_age <months>\n"
            "/set_allergies <comma-separated>\n"
            "/apply <inspiration_id> <day> <slot>\n"
            "/rate <meal_id> <up|down|0> [comment]"
        )
        return ConversationHandler.END
    locale = user.language_code or "en"
    context.user_data["onboarding_locale"] = locale
    context.user_data["onboarding_language"] = locale
    context.user_data["onboarding_age_months"] = 12
    await update.message.reply_text("How old is your baby (in months)? Reply with a number, or 'skip' for 12.")
    return ONBOARDING_AGE


async def onboarding_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return ConversationHandler.END
    age_months = parse_int_or_default(update.message.text or "", 12)
    context.user_data["onboarding_age_months"] = age_months
    await update.message.reply_text("Any allergies? Reply with a comma-separated list, or 'none'.")
    return ONBOARDING_ALLERGIES


async def onboarding_allergies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return ConversationHandler.END
    user = update.effective_user
    if not user:
        return ConversationHandler.END
    allergies = normalize_allergies(update.message.text or "")
    age_months = int(context.user_data.get("onboarding_age_months") or 12)
    preferred_language = str(context.user_data.get("onboarding_language") or (user.language_code or "en"))
    set_profile(user.id, age_months=age_months, allergies=allergies, preferred_language=preferred_language)
    await update.message.reply_text(
        "Onboarding complete.\n\n"
        "Next:\n"
        "/weekly_plan\n"
        "/shopping_list\n"
        "You can also send a photo/link/text inspiration anytime."
    )
    return ConversationHandler.END


async def set_age_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    profile = get_profile(user.id)
    if not profile:
        await update.message.reply_text("Run /start to complete onboarding first.")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("Usage: /set_age <months> (e.g., /set_age 12)")
        return
    age_months = parse_int_or_default(" ".join(args), int(profile.get("age_months") or 12))
    set_profile(
        user.id,
        age_months=age_months,
        allergies=str(profile.get("allergies") or "none"),
        preferred_language=get_user_language(user.id, user.language_code or "en"),
    )
    await update.message.reply_text(f"Updated age to {age_months} months.")


async def set_allergies_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    profile = get_profile(user.id)
    if not profile:
        await update.message.reply_text("Run /start to complete onboarding first.")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("Usage: /set_allergies <comma-separated> (or /set_allergies none)")
        return
    allergies = normalize_allergies(" ".join(args))
    set_profile(
        user.id,
        age_months=int(profile.get("age_months") or 12),
        allergies=allergies,
        preferred_language=get_user_language(user.id, user.language_code or "en"),
    )
    await update.message.reply_text(f"Updated allergies to: {allergies}.")


async def weekly_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    profile = get_profile(user.id)
    if not profile:
        await update.message.reply_text("Run /start to complete onboarding first.")
        return
    language = get_user_language(user.id, user.language_code or "en")
    week_start = week_start_for_plans(date.today())
    existing = get_weekly_plan(user.id, week_start=week_start)
    if existing:
        try:
            plan_obj = json.loads(str(existing["plan_json"]))
        except Exception:
            plan_obj = {"days": {}, "raw": str(existing["plan_json"])}
        await update.message.reply_text(f"Weekly plan (week starting {week_start.isoformat()}):\n\n{render_weekly_plan(plan_obj)}")
        return
    inspirations = get_recent_inspirations(user.id, limit=10)
    await update.message.chat.send_action("typing")
    plan_obj = await generate_weekly_plan(profile=profile, inspirations=inspirations, week_start=week_start, language=language)
    plan_id = upsert_weekly_plan(user.id, week_start=week_start, plan_json=json.dumps(plan_obj, ensure_ascii=False))
    await update.message.reply_text(
        f"Weekly plan created (id: {plan_id}, week starting {week_start.isoformat()}):\n\n{render_weekly_plan(plan_obj)}\n\n"
        "Tip: apply an inspiration into a slot with /apply <inspiration_id> <day> <slot>."
    )


async def shopping_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    profile = get_profile(user.id)
    if not profile:
        await update.message.reply_text("Run /start to complete onboarding first.")
        return
    language = get_user_language(user.id, user.language_code or "en")
    week_start = week_start_for_plans(date.today())
    existing = get_weekly_plan(user.id, week_start=week_start)
    if not existing:
        await update.message.reply_text("No plan yet for next week. Run /weekly_plan first.")
        return
    try:
        plan_obj = json.loads(str(existing["plan_json"]))
    except Exception:
        await update.message.reply_text("I couldn’t read the saved plan. Try /weekly_plan to regenerate.")
        return
    await update.message.chat.send_action("typing")
    list_text = await generate_shopping_list(plan_json=plan_obj, language=language)
    await update.message.reply_text(list_text)


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    plans = get_recent_plans(user.id, limit=3)
    inspirations = get_recent_inspirations(user.id, limit=5)
    lines: list[str] = ["Recent plans:"]
    if plans:
        for p in plans:
            lines.append(f"- id {p['id']} week {p['week_start_date']} (updated {p['updated_at']})")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Recent inspirations:")
    if inspirations:
        for i in inspirations:
            summary = str(i.get("summary") or "")
            summary_short = summary.replace("\n", " ")
            if len(summary_short) > 80:
                summary_short = summary_short[:77] + "..."
            lines.append(f"- id {i['id']} ({i['kind']}): {summary_short}")
    else:
        lines.append("- none")
    await update.message.reply_text("\n".join(lines))


def normalize_day(day: str) -> Optional[str]:
    day = (day or "").strip().lower()
    mapping = {
        "mon": "mon",
        "monday": "mon",
        "tue": "tue",
        "tues": "tue",
        "tuesday": "tue",
        "wed": "wed",
        "wednesday": "wed",
        "thu": "thu",
        "thurs": "thu",
        "thursday": "thu",
        "fri": "fri",
        "friday": "fri",
        "sat": "sat",
        "saturday": "sat",
        "sun": "sun",
        "sunday": "sun",
    }
    return mapping.get(day)


def normalize_slot(slot: str) -> Optional[str]:
    slot = (slot or "").strip().lower()
    mapping = {
        "breakfast": "breakfast",
        "snack1": "snack1",
        "snack2": "snack2",
        "lunch": "lunch",
        "dinner": "dinner",
    }
    return mapping.get(slot)


async def apply_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    profile = get_profile(user.id)
    if not profile:
        await update.message.reply_text("Run /start to complete onboarding first.")
        return
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("Usage: /apply <inspiration_id> <day> <slot> (e.g., /apply 12 mon dinner)")
        return
    try:
        inspiration_id = int(args[0])
    except Exception:
        await update.message.reply_text("Invalid inspiration_id.")
        return
    day_key = normalize_day(args[1])
    slot_key = normalize_slot(args[2])
    if not day_key or not slot_key:
        await update.message.reply_text("Day must be mon..sun and slot must be breakfast/snack1/lunch/snack2/dinner.")
        return
    inspiration = get_inspiration(user.id, inspiration_id)
    if not inspiration:
        await update.message.reply_text("I can’t find that inspiration id.")
        return
    language = get_user_language(user.id, user.language_code or "en")
    week_start = week_start_for_plans(date.today())
    existing = get_weekly_plan(user.id, week_start=week_start)
    if not existing:
        await update.message.reply_text("No plan yet for next week. Run /weekly_plan first.")
        return
    try:
        plan_obj = json.loads(str(existing["plan_json"]))
    except Exception:
        await update.message.reply_text("I couldn’t read the saved plan. Try /weekly_plan to regenerate.")
        return
    await update.message.chat.send_action("typing")
    new_meal = await generate_meal_for_slot(
        profile=profile,
        inspiration_summary=str(inspiration.get("summary") or ""),
        day_key=day_key,
        slot_key=slot_key,
        language=language,
    )
    plan_obj.setdefault("days", {}).setdefault(day_key, {})[slot_key] = new_meal
    plan_id = upsert_weekly_plan(user.id, week_start=week_start, plan_json=json.dumps(plan_obj, ensure_ascii=False))
    await update.message.reply_text(
        f"Updated plan (id: {plan_id}). Replaced {day_key}.{slot_key} with: {new_meal.get('title')}\n\n"
        f"{render_weekly_plan(plan_obj)}"
    )


async def rate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    profile = get_profile(user.id)
    if not profile:
        await update.message.reply_text("Run /start to complete onboarding first.")
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Usage: /rate <meal_id> <up|down|0> [comment] (e.g., /rate tue.lunch up loved it)")
        return
    meal_id = args[0].strip().lower()
    rating_token = args[1].strip().lower()
    rating = 0
    if rating_token in {"up", "+", "+1", "1"}:
        rating = 1
    elif rating_token in {"down", "-", "-1"}:
        rating = -1
    elif rating_token in {"0", "neutral"}:
        rating = 0
    else:
        await update.message.reply_text("Rating must be up, down, or 0.")
        return
    comment = " ".join(args[2:]).strip() if len(args) > 2 else None
    week_start = week_start_for_plans(date.today())
    existing = get_weekly_plan(user.id, week_start=week_start)
    if not existing:
        await update.message.reply_text("No plan yet for next week. Run /weekly_plan first.")
        return
    weekly_plan_id = int(existing["id"])
    now = datetime.utcnow().isoformat()
    with _db_conn() as conn:
        conn.execute(
            """
            INSERT INTO feedback (telegram_user_id, weekly_plan_id, meal_id, rating, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user.id, weekly_plan_id, meal_id, rating, comment, now),
        )
    await update.message.reply_text("Saved feedback. Thank you.")


def main() -> None:
    """Start the bot."""
    logger.info("Starting Baby Feeding Bot...")
    init_db()
    cleanup_retention()
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    onboarding = ConversationHandler(
        entry_points=[CommandHandler("start", onboarding_start)],
        states={
            ONBOARDING_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_age)],
            ONBOARDING_ALLERGIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_allergies)],
        },
        fallbacks=[CommandHandler("help", help_command)],
    )

    application.add_handler(onboarding)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("set_age", set_age_command))
    application.add_handler(CommandHandler("set_allergies", set_allergies_command))
    application.add_handler(CommandHandler("weekly_plan", weekly_plan_command))
    application.add_handler(CommandHandler("shopping_list", shopping_list_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("apply", apply_command))
    application.add_handler(CommandHandler("rate", rate_command))

    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot is running! Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
