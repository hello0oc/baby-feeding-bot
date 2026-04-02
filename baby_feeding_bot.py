#!/usr/bin/env python3
"""
Baby Feeding Bot
Receives inspirations (photos/links/text), generates baby-safe adaptations, and builds weekly meal plans.
"""
from __future__ import annotations

import os
import logging
import base64
import json
import re
import sqlite3
import hashlib
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from typing import Any, Optional, List

import httpx
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from PIL import Image

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
TELEGRAM_BOT_TOKEN = os.environ.get("BABY_FEEDING_BOT_TOKEN")
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY")
MINIMAX_MODEL = "MiniMax-M2.5"
MINIMAX_VISION_MODEL = "MiniMax-VL-01"
DB_PATH = os.environ.get("BABY_FEEDING_DB_PATH", "baby_feeding.sqlite3")
RETENTION_INSPIRATIONS_DAYS = int(os.environ.get("BABY_FEEDING_RETENTION_INSPIRATIONS_DAYS", "90"))
RETENTION_FEEDBACK_DAYS = int(os.environ.get("BABY_FEEDING_RETENTION_FEEDBACK_DAYS", "90"))
RETENTION_PLANS_DAYS = int(os.environ.get("BABY_FEEDING_RETENTION_PLANS_DAYS", "365"))

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("BABY_FEEDING_BOT_TOKEN environment variable not set")
if not MINIMAX_API_KEY:
    raise ValueError("MINIMAX_API_KEY environment variable not set")

MEAL_SYSTEM_PROMPT = """You are a helpful assistant that creates baby-friendly meals for young children.

You must follow parental constraints and baby-safety guidelines.

Guidelines for baby meals:
- Age-appropriate textures (soft, easy to chew/gum)
- Nutritious ingredients
- Simple preparation
- Avoid: honey, choking hazards (whole nuts, whole grapes), excess salt, added sugar, raw/undercooked foods

Respond in a friendly, concise format:
- Keep it practical and encouraging"""

ONBOARDING_AGE, ONBOARDING_ALLERGIES = range(2)

MAIN_MENU_ROWS = [
    ["📅 Weekly plan", "🛒 Shopping list"],
    ["📚 History", "👶 Update age"],
    ["🥜 Update allergies", "🥜 Allergen journal"],
    ["❓ Help"],
]
MENU_TO_ACTION = {
    "📅 Weekly plan": "weekly_plan",
    "🛒 Shopping list": "shopping_list",
    "📚 History": "history",
    "👶 Update age": "update_age",
    "🥜 Update allergies": "update_allergies",
    "🥜 Allergen journal": "allergen_journal",
    "❓ Help": "help",
}
DAY_LABELS = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}
SLOT_LABELS = {
    "breakfast": "Breakfast",
    "snack1": "Morning snack",
    "lunch": "Lunch",
    "snack2": "Afternoon snack",
    "dinner": "Dinner",
}
SLOT_ICONS = {
    "breakfast": "🌅",
    "snack1": "🍎",
    "lunch": "🥗",
    "snack2": "🧃",
    "dinner": "🍲",
}
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", re.IGNORECASE)


def _db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def main_menu_markup() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(MAIN_MENU_ROWS, resize_keyboard=True)


def clean_bullet(text: str) -> str:
    return re.sub(r"^[\-\*\u2022\d\)\.\s]+", "", (text or "").strip())


def compact_lines(text: str) -> List[str]:
    return [clean_bullet(line) for line in (text or "").splitlines() if clean_bullet(line)]


def humanize_timestamp(value: str) -> str:
    if not value:
        return "recently"
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%b %d")
    except Exception:
        return value[:10]


def extract_json_text(text: str) -> Optional[str]:
    if not text:
        return None
    fenced = JSON_BLOCK_RE.search(text)
    if fenced:
        return fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return None


def parse_json_object(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    candidates = [text]
    extracted = extract_json_text(text)
    if extracted and extracted != text:
        candidates.append(extracted)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def normalize_meal_dict(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    if not title:
        return None
    ingredients = raw.get("ingredients")
    if isinstance(ingredients, list):
        normalized_ingredients = [str(item).strip() for item in ingredients if str(item).strip()]
    elif isinstance(ingredients, str) and ingredients.strip():
        normalized_ingredients = [part.strip() for part in ingredients.split(",") if part.strip()]
    else:
        normalized_ingredients = []
    tags = raw.get("tags")
    if isinstance(tags, list):
        normalized_tags = [str(item).strip() for item in tags if str(item).strip()]
    elif isinstance(tags, str) and tags.strip():
        normalized_tags = [part.strip() for part in tags.split(",") if part.strip()]
    else:
        normalized_tags = []
    return {
        "title": title,
        "ingredients": normalized_ingredients,
        "quick_prep": str(raw.get("quick_prep") or "").strip(),
        "safety_note": str(raw.get("safety_note") or "").strip(),
        "tags": normalized_tags,
    }


def normalize_plan_dict(raw: Any, *, week_start: date) -> dict[str, Any]:
    days_raw = raw.get("days") if isinstance(raw, dict) else None
    normalized_days: dict[str, Any] = {}
    if isinstance(days_raw, dict):
        for day_key in DAY_LABELS:
            day_data = days_raw.get(day_key)
            if not isinstance(day_data, dict):
                continue
            normalized_slots: dict[str, Any] = {}
            for slot_key in SLOT_LABELS:
                meal = normalize_meal_dict(day_data.get(slot_key))
                if meal:
                    normalized_slots[slot_key] = meal
            if normalized_slots:
                normalized_days[day_key] = normalized_slots
    plan = {
        "week_start_date": str(raw.get("week_start_date") or week_start.isoformat()) if isinstance(raw, dict) else week_start.isoformat(),
        "days": normalized_days,
    }
    if isinstance(raw, dict) and raw.get("raw"):
        plan["raw"] = raw["raw"]
    if isinstance(raw, dict) and raw.get("error"):
        plan["error"] = raw["error"]
    return plan


def plan_has_content(plan: Optional[dict[str, Any]]) -> bool:
    return bool(plan and isinstance(plan.get("days"), dict) and any(plan["days"].values()))


def format_inspiration_summary(summary: str) -> str:
    lines = compact_lines(summary)
    if not lines:
        return "A new baby-friendly idea is ready."
    if len(lines) == 1:
        return lines[0]
    return "\n".join(f"• {line}" for line in lines[:3])


def render_adaptation_card(index: int, adaptation: str, language: str = "en") -> str:
    lines = compact_lines(adaptation)
    option_label = f"Option {index}" if language == "en" else f"Opción {index}"
    if not lines:
        return f"━━━━━━━━━━━━━━━━━━━━\n{option_label}\n  Generating..."
    # Detect error-like content
    error_signals = ["sorry", "trouble", "couldn't", "failed", "error", "unable"]
    first_line_lower = lines[0].lower() if lines else ""
    if any(signal in first_line_lower for signal in error_signals):
        return f"━━━━━━━━━━━━━━━━━━━━\n{option_label}\n  {lines[0]}"
    title = lines[0]
    body = [f"  {line}" for line in lines[1:5]]
    return f"━━━━━━━━━━━━━━━━━━━━\n{option_label} — {title}\n" + "\n".join(body)


def build_option_picker_keyboard() -> InlineKeyboardMarkup:
    """Build the first keyboard: choose Option 1 or Option 2."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ Option 1", callback_data="opt:1")],
        [InlineKeyboardButton("2️⃣ Option 2", callback_data="opt:2")],
    ])


def build_inspiration_keyboard(option_number: int) -> InlineKeyboardMarkup:
    """
    Build inline keyboard for applying option N to a day/slot.
    Callback data format: selday:{option}:{day} | apply:{option}:{day}:{slot}
    """
    day_groups = [
        [("Mon", "mon"), ("Wed", "wed"), ("Fri", "fri")],
        [("Tue", "tue"), ("Thu", "thu"), ("Sat", "sat"), ("Sun", "sun")],
    ]
    rows = []
    for group in day_groups:
        row = [InlineKeyboardButton(label, callback_data=f"selday:{option_number}:{day_key}") for label, day_key in group]
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def build_slot_keyboard(option_number: int, day_key: str) -> InlineKeyboardMarkup:
    """Build slot buttons after a day is selected."""
    slot_buttons = [
        ("🌅 Breakfast", "breakfast"),
        ("🍎 AM Snack", "snack1"),
        ("🥗 Lunch", "lunch"),
        ("🧃 PM Snack", "snack2"),
        ("🍲 Dinner", "dinner"),
    ]
    rows = []
    row = []
    for i, (label, slot_key) in enumerate(slot_buttons):
        row.append(InlineKeyboardButton(label, callback_data=f"apply:{option_number}:{day_key}:{slot_key}"))
        if len(row) == 3 or i == len(slot_buttons) - 1:
            rows.append(row)
            row = []
    rows.append([InlineKeyboardButton("« Back to days", callback_data=f"back:{option_number}")])
    return InlineKeyboardMarkup(rows)


def render_inspiration_message(summary: str, adaptations: List[str], language: str = "en") -> tuple[str, InlineKeyboardMarkup]:
    intro = "Here's what I found:" if language == "en" else "Esto es lo que encontré:"
    option_prompt = 'Tap "Option 1" or "Option 2" below to choose, then pick a day and meal slot.'
    sections = [
        "✨ Saved your inspiration!",
        "",
        intro,
        format_inspiration_summary(summary),
        "",
        "Baby-friendly options:",
        render_adaptation_card(1, adaptations[0] if len(adaptations) > 0 else "", language),
        "",
        render_adaptation_card(2, adaptations[1] if len(adaptations) > 1 else "", language),
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        option_prompt,
        f"Or reply: Use 1 for Wednesday dinner",
    ]
    text = "\n".join(section for section in sections if section is not None).strip()
    keyboard = build_option_picker_keyboard()
    return text, keyboard


def render_meal_card(meal: dict[str, Any], slot_key: str, language: str = "en") -> str:
    title = meal.get("title", "Meal")
    ingredients = meal.get("ingredients") or []
    quick_prep = meal.get("quick_prep", "").strip()
    safety_note = meal.get("safety_note", "").strip()
    tags = meal.get("tags") or []
    tag_display = f" [{', '.join(tags[:3])}]" if tags and isinstance(tags, list) else ""

    lines = [
        f"🍽️  {title}{tag_display}",
        "",
    ]
    if ingredients:
        ing_text = ", ".join(ingredients[:8])
        if len(ing_text) > 60:
            ing_text = ", ".join(ingredients[:6]) + "..."
        lines.append(f"   📋 {ing_text}")
    if quick_prep:
        lines.append(f"   ⚡ {quick_prep}")
    if safety_note:
        lines.append(f"   ⚠️  {safety_note}")
    return "\n".join(lines)


def render_weekly_plan(plan: dict[str, Any], language: str = "en") -> str:
    days = plan.get("days") or {}
    if not days:
        return "No meals planned yet." if language == "en" else "Aún no hay comidas planificadas."

    lines: List[str] = ["📅 Weekly Plan", "━━━━━━━━━━━━━━━━━━━━", ""]
    for day_key, day_label in DAY_LABELS.items():
        day = days.get(day_key)
        if not isinstance(day, dict):
            continue
        meals_in_day = [slot_key for slot_key in SLOT_LABELS if day.get(slot_key)]
        if not meals_in_day:
            continue

        lines.append(f"📆 {day_label}")
        for slot_key, slot_label in SLOT_LABELS.items():
            meal = day.get(slot_key)
            if not isinstance(meal, dict):
                continue
            lines.append(render_meal_card(meal, slot_key, language))
        lines.append("")

    return "\n".join(lines).strip()


def render_single_meal(day_key: str, slot_key: str, meal: dict[str, Any], language: str = "en") -> str:
    day_label = DAY_LABELS.get(day_key, day_key.title())
    slot_label = SLOT_LABELS.get(slot_key, slot_key).lower()
    lines = [
        f"✅ Updated {day_label} {slot_label}",
        "",
        render_meal_card(meal, slot_key, language),
    ]
    return "\n".join(lines)


def render_history_message(plans: List[dict[str, Any]], inspirations: List[dict[str, Any]], language: str = "en") -> str:
    plans_header = "📚 Recent Plans" if language == "en" else "📚 Planes Recientes"
    inspirations_header = "💡 Recent Inspirations" if language == "en" else "💡 Inspiraciones Recientes"
    no_plans = "• No weekly plans yet." if language == "en" else "• Aún no hay planes semanales."
    no_inspirations = "• No saved inspirations yet." if language == "en" else "• Aún no hay inspiraciones guardadas."

    lines = [plans_header, ""]
    if plans:
        for plan in plans:
            lines.append(
                f"• Week of {plan.get('week_start_date', 'unknown')} — "
                f"updated {humanize_timestamp(str(plan.get('updated_at') or ''))}"
            )
    else:
        lines.append(no_plans)
    lines.extend(["", inspirations_header, ""])
    if inspirations:
        for inspiration in inspirations:
            summary_short = " ".join(compact_lines(str(inspiration.get("summary") or "")))
            if len(summary_short) > 90:
                summary_short = summary_short[:87] + "..."
            kind = str(inspiration.get("kind") or "idea").capitalize()
            lines.append(f"• {kind}: {summary_short or 'Saved idea'}")
    else:
        lines.append(no_inspirations)
    return "\n".join(lines)


def format_shopping_list_message(list_text: str, language: str = "en") -> str:
    cleaned = (list_text or "").strip()
    if not cleaned:
        fallback = "I couldn't build a shopping list yet. Please try again after generating a weekly plan."
        if language != "en":
            fallback = "No pude crear una lista de compras. Inténtalo de nuevo después de generar un plan semanal."
        return f"🛒 Shopping List\n\n{fallback}"
    header = "🛒 Shopping List" if language == "en" else "🛒 Lista de Compras"
    return f"{header}\n━━━━━━━━━━━━━━━━━━━━\n\n{cleaned}"


def parse_quick_apply_text(text: str) -> Optional[tuple[int, str, str]]:
    normalized = " ".join((text or "").strip().split())
    match = re.match(
        r"^(?:use|apply)\s+([12])(?:\s+(?:for|to|on))?\s+([a-zA-Z]+)\s+([a-zA-Z0-9 ]+)$",
        normalized,
        re.IGNORECASE,
    )
    if not match:
        return None
    option_number = int(match.group(1))
    day_key = normalize_day(match.group(2))
    slot_key = normalize_slot(match.group(3))
    if not day_key or not slot_key:
        return None
    return option_number, day_key, slot_key


def get_adaptation_by_index(inspiration: dict[str, Any], option_number: int) -> str:
    try:
        adaptations = json.loads(str(inspiration.get("adaptations_json") or "[]"))
    except Exception:
        adaptations = []
    if isinstance(adaptations, list):
        index = option_number - 1
        if 0 <= index < len(adaptations):
            return str(adaptations[index] or "").strip()
    return ""


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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS allergen_intros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                allergen TEXT NOT NULL,
                introduced_at TEXT NOT NULL,
                reactions TEXT,
                FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id),
                UNIQUE(telegram_user_id, allergen)
            )
            """
        )
        # Add introduced_allergens column if it doesn't exist (safe migration)
        try:
            conn.execute("ALTER TABLE profiles ADD COLUMN introduced_allergens TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # Column already exists


def cleanup_retention() -> None:
    now = datetime.now(UTC)
    inspirations_cutoff = (now - timedelta(days=RETENTION_INSPIRATIONS_DAYS)).isoformat()
    feedback_cutoff = (now - timedelta(days=RETENTION_FEEDBACK_DAYS)).isoformat()
    plans_cutoff_date = (now.date() - timedelta(days=RETENTION_PLANS_DAYS)).isoformat()
    with _db_conn() as conn:
        conn.execute("DELETE FROM inspirations WHERE created_at < ?", (inspirations_cutoff,))
        conn.execute("DELETE FROM feedback WHERE created_at < ?", (feedback_cutoff,))
        conn.execute("DELETE FROM weekly_plans WHERE week_start_date < ?", (plans_cutoff_date,))


def upsert_user(telegram_user_id: int, locale: Optional[str]) -> None:
    now = datetime.now(UTC).isoformat()
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
    now = datetime.now(UTC).isoformat()
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


ALLERGEN_TRACK_LIST = ["milk", "egg", "peanut", "tree nuts", "soy", "wheat", "fish", "shellfish", "sesame"]


def get_introduced_allergens(telegram_user_id: int) -> List[str]:
    """Return list of allergens already introduced for this user."""
    with _db_conn() as conn:
        rows = conn.execute(
            "SELECT allergen FROM allergen_intros WHERE telegram_user_id = ?",
            (telegram_user_id,),
        ).fetchall()
        return [str(r["allergen"]).lower() for r in rows]


def introduce_allergen(telegram_user_id: int, allergen: str, reactions: Optional[str] = None) -> bool:
    """Log a new allergen introduction. Returns True if new, False if already existed."""
    allergen_normalized = allergen.lower().strip()
    now = datetime.now(UTC).isoformat()
    try:
        with _db_conn() as conn:
            conn.execute(
                """
                INSERT INTO allergen_intros (telegram_user_id, allergen, introduced_at, reactions)
                VALUES (?, ?, ?, ?)
                """,
                (telegram_user_id, allergen_normalized, now, reactions),
            )
        # Update profiles column too
        with _db_conn() as conn:
            existing = conn.execute(
                "SELECT introduced_allergens FROM profiles WHERE telegram_user_id = ?",
                (telegram_user_id,),
            ).fetchone()
            if existing:
                existing_list = [a.strip() for a in str(existing["introduced_allergens"] or "").split(",") if a.strip()]
                if allergen_normalized not in existing_list:
                    existing_list.append(allergen_normalized)
                conn.execute(
                    "UPDATE profiles SET introduced_allergens = ? WHERE telegram_user_id = ?",
                    (", ".join(existing_list), telegram_user_id),
                )
        return True
    except sqlite3.IntegrityError:
        return False  # Already existed


def get_allergen_journal(telegram_user_id: int) -> List[dict[str, Any]]:
    """Return all allergen introductions for this user."""
    with _db_conn() as conn:
        rows = conn.execute(
            "SELECT allergen, introduced_at, reactions FROM allergen_intros WHERE telegram_user_id = ? ORDER BY introduced_at DESC",
            (telegram_user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_meal_rating_stats(telegram_user_id: int, week_start: date) -> dict[str, Any]:
    """
    Return rating stats: avg per slot, per day, per tag, and total count.
    Only considers meals within the last 12 weeks.
    """
    cutoff = (datetime.now(UTC) - timedelta(weeks=12)).isoformat()
    with _db_conn() as conn:
        rows = conn.execute(
            """
            SELECT f.meal_id, f.rating, f.created_at, p.plan_json
            FROM feedback f
            JOIN weekly_plans p ON f.weekly_plan_id = p.id
            WHERE f.telegram_user_id = ? AND f.created_at >= ?
            ORDER BY f.created_at DESC
            """,
            (telegram_user_id, cutoff),
        ).fetchall()

    if not rows:
        return {}

    slot_avg: dict[str, float] = {}
    slot_count: dict[str, int] = {}
    tag_avg: dict[str, float] = {}
    tag_count: dict[str, int] = {}
    total = 0
    total_rating = 0.0

    for row in rows:
        rating = int(row["rating"] or 0)
        meal_id = str(row["meal_id"] or "")
        total += 1
        total_rating += rating

        # Parse slot from meal_id like "wed.breakfast"
        if "." in meal_id:
            parts = meal_id.split(".", 1)
            day_key, slot_key = parts[0], parts[1]
        else:
            day_key, slot_key = "", ""

        if slot_key:
            slot_avg[slot_key] = slot_avg.get(slot_key, 0.0) + rating
            slot_count[slot_key] = slot_count.get(slot_key, 0) + 1

        # Get tags from plan_json for this meal
        try:
            plan = json.loads(str(row["plan_json"]))
            day_data = (plan.get("days") or {}).get(day_key, {})
            meal = day_data.get(slot_key, {})
            for tag in (meal.get("tags") or []):
                tag_avg[tag] = tag_avg.get(tag, 0.0) + rating
                tag_count[tag] = tag_count.get(tag, 0) + 1
        except Exception:
            pass

    # Average
    for k in slot_avg:
        if slot_count[k] > 0:
            slot_avg[k] = round(slot_avg[k] / slot_count[k], 2)

    for k in tag_avg:
        if tag_count[k] > 0:
            tag_avg[k] = round(tag_avg[k] / tag_count[k], 2)

    return {
        "total_meals": total,
        "avg_rating": round(total_rating / total, 2) if total > 0 else 0.0,
        "slot_avg": slot_avg,
        "tag_avg": tag_avg,
    }


def get_negatively_rated_meal_ids(telegram_user_id: int) -> set[str]:
    """Return meal IDs that were consistently rated negatively (avg < 0)."""
    stats = get_meal_rating_stats(telegram_user_id, datetime.now(UTC).date())
    slot_avg = stats.get("slot_avg", {})
    # We need per-slot-per-day ratings, so we check individual feedback rows
    cutoff = (datetime.now(UTC) - timedelta(weeks=12)).isoformat()
    meal_neg_count: dict[str, int] = {}
    meal_total_count: dict[str, int] = {}
    with _db_conn() as conn:
        rows = conn.execute(
            """
            SELECT f.meal_id, f.rating, p.plan_json
            FROM feedback f
            JOIN weekly_plans p ON f.weekly_plan_id = p.id
            WHERE f.telegram_user_id = ? AND f.created_at >= ?
            """,
            (telegram_user_id, cutoff),
        ).fetchall()
    for row in rows:
        meal_id = str(row["meal_id"] or "")
        rating = int(row["rating"] or 0)
        meal_neg_count[meal_id] = meal_neg_count.get(meal_id, 0) + (1 if rating < 0 else 0)
        meal_total_count[meal_id] = meal_total_count.get(meal_id, 0) + 1
    result = set()
    for meal_id, total in meal_total_count.items():
        if total >= 2 and meal_neg_count.get(meal_id, 0) / total > 0.5:
            result.add(meal_id)
    return result


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


async def llm_generate(
    prompt: str,
    *,
    system_prompt: str = "",
    temperature: float = 0.4,
    max_tokens: int = 2048,
) -> str:
    """
    Generate text using MiniMax M2.5 via the Anthropic Messages API endpoint.
    """
    friendly_error = "Sorry, I had trouble generating a response right now."
    messages = []
    if system_prompt:
        messages.append({"role": "developer", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": MINIMAX_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "thinking": {"type": "disabled"},
    }
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                "https://api.minimaxi.com/anthropic/v1/messages",
                headers={
                    "Authorization": f"Bearer {MINIMAX_API_KEY}",
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01",
                },
                json=payload,
                timeout=60.0,
            )
            if response.status_code != 200:
                logger.error("MiniMax API error: %s - %s", response.status_code, response.text[:200])
                return friendly_error
            result = response.json()
            text = str(result.get("content", [{}])[0].get("text", "").strip())
            if not text:
                logger.error("MiniMax API returned blank text")
                return friendly_error
            return text
    except Exception as e:
        logger.error("MiniMax API exception: %s", e)
        return friendly_error


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
    if not update.message:
        return
    language = get_user_language(update.effective_user.id, update.effective_user.language_code or "en")
    if language == "es":
        help_text = (
            "Aquí te ayudo:\n\n"
            "1. Envía una foto de comida, un enlace o una idea de comida.\n"
            "2. Te daré opciones seguras para tu bebé.\n"
            "3. Responde con algo como \"Use 1 for Wednesday dinner\" para añadirlo al plan.\n\n"
            "Usa los botones del menú para ver tu plan semanal, lista de compras, historial y más."
        )
    else:
        help_text = (
            "Here's how to use me:\n\n"
            "1. Send a food photo, a link, or a short meal idea.\n"
            "2. I'll turn it into baby-friendly options.\n"
            "3. Reply with something like \"Use 1 for Wednesday dinner\" to add it to your plan.\n\n"
            "You can also use the menu buttons below for your weekly plan, shopping list, history, and profile updates."
        )
    await update.message.reply_text(help_text, reply_markup=main_menu_markup())


async def analyze_image_for_inspiration(image_bytes: bytes, *, language: str) -> str:
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
    if language == "es":
        prompt = (
            "Describe the food shown and extract a short theme I can use as a meal inspiration.\n"
            "Return 2-3 bullet points.\n"
            "Respond in language: Spanish"
        )
    else:
        prompt = (
            "Describe the food shown and extract a short theme I can use as a meal inspiration.\n"
            "Return 2-3 bullet points.\n"
            "Respond in language: English"
        )
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_str}},
            ],
        }
    ]
    payload = {
        "model": MINIMAX_VISION_MODEL,
        "messages": messages,
        "max_tokens": 512,
        "temperature": 0.3,
        "thinking": {"type": "disabled"},
    }
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                "https://api.minimaxi.com/anthropic/v1/messages",
                headers={
                    "Authorization": f"Bearer {MINIMAX_API_KEY}",
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01",
                },
                json=payload,
                timeout=60.0,
            )
            if response.status_code != 200:
                logger.error("MiniMax image analysis error: %s", response.status_code)
                return "Sorry, I had trouble analyzing that image." if language == "en" else "Lo siento, tuve problemas analizando esa imagen."
            result = response.json()
            text = str(result.get("content", [{}])[0].get("text", "").strip())
            return text if text else ("Sorry, I had trouble analyzing that image." if language == "en" else "Lo siento, tuve problemas analizando esa imagen.")
    except Exception as e:
        logger.error("MiniMax image analysis exception: %s", e)
        return "Sorry, I had trouble analyzing that image." if language == "en" else "Lo siento, tuve problemas analizando esa imagen."


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


def age_safety_rules_text(profile: Optional[dict[str, Any]]) -> str:
    age = int(profile.get("age_months", 12)) if profile else 12

    if age < 6:
        stage = "4-6 months: Puree stage — smooth, no lumps, single ingredient, iron-fortified cereals preferred"
        warning = "⚠️ Always supervise. Introduce one new food every 3-4 days."
    elif age < 9:
        stage = "6-9 months: Smooth to slightly textured — mashed banana, avocado, well-cooked mashed vegetables"
        warning = "⚠️ Always supervise. No round foods (whole grapes, cherry tomatoes). Mash or cut grapes in half."
    elif age < 12:
        stage = "9-12 months: Finger food introduction — soft strips, pincer grasp foods, no round hard foods (whole grapes, nuts)"
        warning = "⚠️ Always supervise. Avoid nuts, seeds, whole grapes, hard raw vegetables. Cut foods into thin strips."
    elif age < 18:
        stage = "12-18 months: Family food adaptation — soft pieces, modified texture, self-feeding encouraged"
        warning = "⚠️ Always supervise eating. Continue avoiding nuts, hard raw foods, and choking hazards."
    elif age < 24:
        stage = "18-24 months: Transitional — near-adult foods with reduced sodium, modified only for sugar/salt"
        warning = "⚠️ Always supervise. Limit processed foods, excess sodium, and added sugars."
    else:
        stage = "24+ months: Near-adult — family meals with minimal modifications"
        warning = "⚠️ Always supervise. Keep modifications minimal; focus on balanced portions."

    return f"Current feeding stage ({stage})\n{warning}"


async def generate_two_adaptations(*, inspiration: str, profile: Optional[dict[str, Any]], language: str) -> List[str]:
    system = MEAL_SYSTEM_PROMPT
    if language == "es":
        system = system.replace("You are a helpful assistant", "Eres un asistente útil")

    age_safety = age_safety_rules_text(profile)
    prompt = (
        f"Task: Based on the inspiration, propose exactly 2 baby-safe meal adaptations.\n"
        "Each adaptation must be 3-5 lines:\n"
        "- Meal name\n"
        "- Key ingredients\n"
        "- Quick prep\n"
        "- Safety note\n\n"
        f"Constraints:\n{profile_constraints_text(profile)}\n\n"
        f"Age-specific safety:\n{age_safety}\n\n"
        f"Inspiration:\n{inspiration}\n\n"
        f"Respond in language: {'Spanish' if language == 'es' else 'English'}"
    )
    text = await llm_generate(prompt, system_prompt=system, temperature=0.4, max_tokens=700)
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) >= 2:
        return [blocks[0], blocks[1]]
    return [text.strip(), ""]


def store_inspiration(
    telegram_user_id: int,
    *,
    kind: str,
    summary: str,
    adaptations: List[str],
    source_url: Optional[str] = None,
    image_sha: Optional[str] = None,
) -> int:
    now = datetime.now(UTC).isoformat()
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


def get_recent_inspirations(telegram_user_id: int, limit: int = 5) -> List[dict[str, Any]]:
    with _db_conn() as conn:
        rows = conn.execute(
            "SELECT id, kind, source_url, created_at, summary FROM inspirations WHERE telegram_user_id = ? ORDER BY id DESC LIMIT ?",
            (telegram_user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_latest_inspiration(telegram_user_id: int) -> Optional[dict[str, Any]]:
    with _db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM inspirations WHERE telegram_user_id = ? ORDER BY id DESC LIMIT 1",
            (telegram_user_id,),
        ).fetchone()
        return dict(row) if row else None


def upsert_weekly_plan(telegram_user_id: int, *, week_start: date, plan_json: str) -> int:
    now = datetime.now(UTC).isoformat()
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


def get_recent_plans(telegram_user_id: int, limit: int = 3) -> List[dict[str, Any]]:
    with _db_conn() as conn:
        rows = conn.execute(
            "SELECT id, week_start_date, created_at, updated_at FROM weekly_plans WHERE telegram_user_id = ? ORDER BY week_start_date DESC LIMIT ?",
            (telegram_user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


async def generate_weekly_plan(
    *,
    profile: Optional[dict[str, Any]],
    inspirations: List[dict[str, Any]],
    week_start: date,
    language: str,
    telegram_user_id: int = 0,
) -> dict[str, Any]:
    inspiration_text = "\n".join([f"- {i.get('summary', '')}".strip() for i in inspirations if i.get("summary")]) or "none"
    system = MEAL_SYSTEM_PROMPT
    if language == "es":
        system = system.replace("You are a helpful assistant", "Eres un asistente útil")

    age_safety = age_safety_rules_text(profile)
    age_months = int(profile.get("age_months", 12)) if profile else 12

    # Check for feedback insights
    feedback_insight = ""
    if telegram_user_id:
        stats = get_meal_rating_stats(telegram_user_id, week_start)
        if stats and stats.get("total_meals", 0) >= 3:
            insights = []
            slot_avg = stats.get("slot_avg", {})
            if slot_avg:
                for slot, avg in slot_avg.items():
                    if avg > 0.3:
                        insights.append(f"user rates {slot} positively")
                if insights:
                    feedback_insight = "\n".join(insights)

    prompt = (
        f"Create a weekly meal plan for a {age_months}-month-old.\n"
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
        f"Age-specific safety:\n{age_safety}\n\n"
        f"Week starts: {week_start.isoformat()}\n"
        f"Inspirations (themes):\n{inspiration_text}\n\n"
        f"{'Based on past feedback, user prefers: ' + feedback_insight + '\n\n' if feedback_insight else ''}"
        "Return ONLY valid JSON matching this top-level shape:\n"
        '{ "week_start_date": "YYYY-MM-DD", "days": { "mon": { "breakfast": {...}, "snack1": {...}, "lunch": {...}, "snack2": {...}, "dinner": {...} }, "...": "..." } }\n\n'
        f"Respond in language: {'Spanish' if language == 'es' else 'English'}"
    )
    text = await llm_generate(prompt, system_prompt=system, temperature=0.5, max_tokens=2500)
    parsed = parse_json_object(text)
    if not parsed:
        return {"week_start_date": week_start.isoformat(), "days": {}, "raw": text, "error": "parse_failed"}
    normalized = normalize_plan_dict(parsed, week_start=week_start)
    if plan_has_content(normalized):
        return normalized
    normalized["raw"] = text
    normalized["error"] = "empty_plan"
    return normalized


async def generate_shopping_list(*, plan_json: dict[str, Any], language: str, telegram_user_id: int = 0) -> str:
    # Get negatively rated meal IDs to skip
    negative_meal_ids = set()
    if telegram_user_id:
        negative_meal_ids = get_negatively_rated_meal_ids(telegram_user_id)

    # Filter out negatively rated meals from plan
    filtered_plan = plan_json.copy()
    if "days" in filtered_plan:
        for day_key, day_data in list(filtered_plan.get("days", {}).items()):
            if isinstance(day_data, dict):
                for slot_key, meal in list(day_data.items()):
                    meal_id = f"{day_key}.{slot_key}"
                    if meal_id in negative_meal_ids:
                        del day_data[slot_key]

    prompt = (
        "Create a consolidated shopping list grouped by category (produce, protein, dairy, pantry, other).\n"
        "Avoid adding salt/sugar items. Keep it concise.\n\n"
        f"Plan JSON:\n{json.dumps(filtered_plan, ensure_ascii=False)}\n\n"
        f"Respond in language: {'Spanish' if language == 'es' else 'English'}"
    )
    return await llm_generate(prompt, temperature=0.2, max_tokens=1200)


async def generate_meal_for_slot(
    *,
    profile: Optional[dict[str, Any]],
    inspiration_summary: str,
    selected_adaptation: str,
    day_key: str,
    slot_key: str,
    language: str,
) -> dict[str, Any]:
    system = MEAL_SYSTEM_PROMPT
    if language == "es":
        system = system.replace("You are a helpful assistant", "Eres un asistente útil")

    age_safety = age_safety_rules_text(profile)

    prompt = (
        "Create a single meal for the specified day+slot, inspired by the inspiration.\n"
        "Return ONLY valid JSON with keys: title, ingredients (array), quick_prep, safety_note, tags (array).\n\n"
        f"Constraints:\n{profile_constraints_text(profile)}\n\n"
        f"Age-specific safety:\n{age_safety}\n\n"
        f"Day: {day_key}\nSlot: {slot_key}\n"
        f"Inspiration:\n{inspiration_summary}\n\n"
        f"Preferred adaptation direction:\n{selected_adaptation or 'Use the best fit for this slot.'}\n\n"
        f"Respond in language: {'Spanish' if language == 'es' else 'English'}"
    )
    text = await llm_generate(prompt, system_prompt=system, temperature=0.45, max_tokens=900)
    parsed = parse_json_object(text)
    meal = normalize_meal_dict(parsed)
    if meal:
        return meal
    return {"error": "parse_failed", "raw": text}


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    language = get_user_language(user.id, user.language_code or "en")
    await update.message.chat.send_action("typing")
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = bytes(await file.download_as_bytearray())
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
        context.user_data["last_inspiration_id"] = inspiration_id
        msg_text, keyboard = render_inspiration_message(inspiration_summary, adaptations, language)
        await update.message.reply_text(msg_text, reply_markup=keyboard)
    except Exception as e:
        logger.error("Error handling photo: %s", e)
        error_msg = (
            "Sorry, I couldn't process that image. Please try another photo or send a text idea instead."
            if language == "en"
            else "Lo siento, no pude procesar esa imagen. Prueba con otra foto o envía una idea de comida."
        )
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())


async def handle_apply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard callbacks for applying inspirations to meal slots."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    user = query.from_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    language = get_user_language(user.id, user.language_code or "en")
    profile = get_profile(user.id)

    data = query.data or ""
    parts = data.split(":")
    action = parts[0] if parts else ""

    if action == "opt":
        # Option 1 or 2 selected → show day picker for that option
        try:
            option_number = int(parts[1])
        except (ValueError, IndexError):
            option_number = 1
        keyboard = build_inspiration_keyboard(option_number)
        context.user_data["selected_option"] = option_number
        try:
            await query.edit_message_reply_markup(reply_markup=keyboard)
        except Exception:
            pass
        return

    if action == "back":
        # Return to option picker
        keyboard = build_option_picker_keyboard()
        try:
            await query.edit_message_reply_markup(reply_markup=keyboard)
        except Exception:
            pass
        return

    if action == "selday":
        # Day selected → show slot buttons
        try:
            option_number = int(parts[1])
            day_key = parts[2]
        except (ValueError, IndexError):
            option_number = context.user_data.get("selected_option", 1)
            day_key = parts[1] if len(parts) > 1 else "mon"
        keyboard = build_slot_keyboard(option_number, day_key)
        context.user_data[f"selected_day_opt{option_number}"] = day_key
        try:
            await query.edit_message_reply_markup(reply_markup=keyboard)
        except Exception:
            pass
        return

    if action == "apply":
        # Apply option to day/slot
        try:
            option_number = int(parts[1])
            day_key = parts[2]
            slot_key = parts[3]
        except (ValueError, IndexError):
            await query.answer("Invalid selection", show_alert=True)
            return

        if not profile:
            await query.answer("Please run /start first.", show_alert=True)
            return

        inspiration_id = context.user_data.get("last_inspiration_id")
        inspiration = get_inspiration(user.id, int(inspiration_id)) if inspiration_id else get_latest_inspiration(user.id)
        if not inspiration:
            await query.answer("No inspiration found. Send a photo or idea first.", show_alert=True)
            return

        week_start = week_start_for_plans(date.today())
        existing = get_weekly_plan(user.id, week_start=week_start)
        if not existing:
            await query.answer("No weekly plan yet. Tap Weekly plan first.", show_alert=True)
            return

        try:
            plan_obj = normalize_plan_dict(json.loads(str(existing["plan_json"])), week_start=week_start)
        except Exception:
            await query.answer("Couldn't read your plan. Try refreshing.", show_alert=True)
            return

        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_chat_action(query.message.chat_id, "typing")

        selected_adaptation = get_adaptation_by_index(inspiration, option_number)
        new_meal = await generate_meal_for_slot(
            profile=profile,
            inspiration_summary=str(inspiration.get("summary") or ""),
            selected_adaptation=selected_adaptation,
            day_key=day_key,
            slot_key=slot_key,
            language=language,
        )
        normalized_meal = normalize_meal_dict(new_meal)
        if not normalized_meal:
            await context.bot.send_message(
                query.message.chat_id,
                "I couldn't safely turn that idea into a meal right now. Please try another idea.",
                reply_markup=main_menu_markup(),
            )
            return

        plan_obj.setdefault("days", {}).setdefault(day_key, {})[slot_key] = normalized_meal
        upsert_weekly_plan(user.id, week_start=week_start, plan_json=json.dumps(plan_obj, ensure_ascii=False))

        day_label = DAY_LABELS.get(day_key, day_key.title())
        slot_label = SLOT_LABELS.get(slot_key, slot_key).lower()
        confirm = f"✅ Applied Option {option_number} to {day_label} {slot_label}!"
        await context.bot.send_message(
            query.message.chat_id,
            f"{confirm}\n\n{render_weekly_plan(plan_obj, language)}",
            reply_markup=main_menu_markup(),
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    # Greeting / noise filter
    greeting_patterns = [
        r"^(hi|hello|hey|hola|good morning|good evening|buenos días|qué tal|howdy)$",
        r"^start$",
    ]
    is_greeting = any(re.match(p, text.lower()) for p in greeting_patterns)
    is_noise = len(text) <= 2 and not text.isalnum()  # pure emoji or single char
    if is_greeting or is_noise:
        await update.message.reply_text(
            "Hi! Send a food photo or meal idea to get started, or tap a menu button.",
            reply_markup=main_menu_markup(),
        )
        return

    action = MENU_TO_ACTION.get(text)
    if action == "weekly_plan":
        await weekly_plan_command(update, context)
        return
    if action == "shopping_list":
        await shopping_list_command(update, context)
        return
    if action == "history":
        await history_command(update, context)
        return
    if action == "help":
        await help_command(update, context)
        return
    if action == "update_age":
        context.user_data["awaiting_age_update"] = True
        context.user_data.pop("awaiting_allergies_update", None)
        prompt = "Please send your baby's age in months, for example: 12"
        if language == "es":
            prompt = "Por favor envía la edad de tu bebé en meses, por ejemplo: 12"
        await update.message.reply_text(prompt, reply_markup=main_menu_markup())
        return
    if action == "update_allergies":
        context.user_data["awaiting_allergies_update"] = True
        context.user_data.pop("awaiting_age_update", None)
        prompt = "Please send allergies as a comma-separated list, or reply with none."
        if language == "es":
            prompt = "Por favor envía las alergias como una lista separada por comas, o responde con none."
        await update.message.reply_text(prompt, reply_markup=main_menu_markup())
        return
    if action == "allergen_journal":
        await allergen_journal_command(update, context)
        return
    urls = URL_RE.findall(text)
    profile = get_profile(user.id)
    if context.user_data.pop("awaiting_age_update", False):
        if not profile:
            error_msg = "Please run /start first so I can save your profile."
            if language == "es":
                error_msg = "Por favor usa /start primero para guardar tu perfil."
            await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
            return
        age_months = parse_int_or_default(text, int(profile.get("age_months") or 12))
        set_profile(
            user.id,
            age_months=age_months,
            allergies=str(profile.get("allergies") or "none"),
            preferred_language=language,
        )
        response = f"Updated age to {age_months} months."
        if language == "es":
            response = f"Edad actualizada a {age_months} meses."
        await update.message.reply_text(response, reply_markup=main_menu_markup())
        return
    if context.user_data.pop("awaiting_allergies_update", False):
        if not profile:
            error_msg = "Please run /start first so I can save your profile."
            if language == "es":
                error_msg = "Por favor usa /start primero para guardar tu perfil."
            await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
            return
        allergies = normalize_allergies(text)
        set_profile(
            user.id,
            age_months=int(profile.get("age_months") or 12),
            allergies=allergies,
            preferred_language=language,
        )
        response = f"Updated allergies to: {allergies}."
        if language == "es":
            response = f"Alergias actualizadas a: {allergies}."
        await update.message.reply_text(response, reply_markup=main_menu_markup())
        return
    quick_apply = parse_quick_apply_text(text)
    if quick_apply:
        option_number, day_key, slot_key = quick_apply
        if not profile:
            error_msg = "Please run /start first so I can create your profile."
            if language == "es":
                error_msg = "Por favor usa /start primero para crear tu perfil."
            await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
            return
        inspiration_id = context.user_data.get("last_inspiration_id")
        inspiration = get_inspiration(user.id, int(inspiration_id)) if inspiration_id else get_latest_inspiration(user.id)
        if not inspiration:
            error_msg = "I don't have a recent inspiration to place yet. Send a photo, link, or meal idea first."
            if language == "es":
                error_msg = "No tengo una inspiración reciente para colocar. Envía una foto, enlace o idea de comida primero."
            await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
            return
        week_start = week_start_for_plans(date.today())
        existing = get_weekly_plan(user.id, week_start=week_start)
        if not existing:
            error_msg = "I need a weekly plan first. Tap Weekly plan and I'll build one for you."
            if language == "es":
                error_msg = "Primero necesito un plan semanal. Toca Plan semanal y yo crearé uno para ti."
            await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
            return
        try:
            plan_obj = normalize_plan_dict(json.loads(str(existing["plan_json"])), week_start=week_start)
        except Exception:
            error_msg = "I couldn't read your current plan. Tap Weekly plan to refresh it."
            if language == "es":
                error_msg = "No pude leer tu plan actual. Toca Plan semanal para actualizzarlo."
            await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
            return
        await update.message.chat.send_action("typing")
        selected_adaptation = get_adaptation_by_index(inspiration, option_number)
        new_meal = await generate_meal_for_slot(
            profile=profile,
            inspiration_summary=str(inspiration.get("summary") or ""),
            selected_adaptation=selected_adaptation,
            day_key=day_key,
            slot_key=slot_key,
            language=language,
        )
        normalized_meal = normalize_meal_dict(new_meal)
        if not normalized_meal:
            error_msg = "I couldn't safely turn that idea into a meal right now. Please try another idea or regenerate the weekly plan."
            if language == "es":
                error_msg = "No pude convertir esa idea en una comida ahora. Prueba con otra idea o regenera el plan semanal."
            await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
            return
        plan_obj.setdefault("days", {}).setdefault(day_key, {})[slot_key] = normalized_meal
        upsert_weekly_plan(user.id, week_start=week_start, plan_json=json.dumps(plan_obj, ensure_ascii=False))
        await update.message.reply_text(
            f"{render_single_meal(day_key, slot_key, normalized_meal, language)}\n\n{render_weekly_plan(plan_obj, language)}",
            reply_markup=main_menu_markup(),
        )
        return
    await update.message.chat.send_action("typing")
    if urls:
        url = urls[0]
        summary_prompt = (
            "Extract a short theme from this link context suitable as a meal inspiration.\n"
            "Return 2-3 bullet points.\n\n"
            f"Link: {url}\n"
            f"Message context: {text}\n\n"
            f"Respond in language: {'Spanish' if language == 'es' else 'English'}"
        )
        inspiration_summary = await llm_generate(summary_prompt, temperature=0.3, max_tokens=400)
        adaptations = await generate_two_adaptations(inspiration=inspiration_summary, profile=profile, language=language)
        inspiration_id = store_inspiration(
            user.id,
            kind="link",
            source_url=url,
            summary=inspiration_summary,
            adaptations=adaptations,
        )
        context.user_data["last_inspiration_id"] = inspiration_id
        msg_text, keyboard = render_inspiration_message(inspiration_summary, adaptations, language)
        await update.message.reply_text(msg_text, reply_markup=keyboard)
        return
    inspiration_summary = text
    adaptations = await generate_two_adaptations(inspiration=inspiration_summary, profile=profile, language=language)
    inspiration_id = store_inspiration(
        user.id,
        kind="text",
        summary=inspiration_summary,
        adaptations=adaptations,
    )
    context.user_data["last_inspiration_id"] = inspiration_id
    msg_text, keyboard = render_inspiration_message(inspiration_summary, adaptations, language)
    await update.message.reply_text(msg_text, reply_markup=keyboard)


async def onboarding_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return ConversationHandler.END
    user = update.effective_user
    if not user:
        return ConversationHandler.END
    upsert_user(user.id, user.language_code)
    profile = get_profile(user.id)
    if profile:
        welcome = (
            "Welcome back 👋\n\n"
            "What would you like to do today?\n"
            "• Build or view your weekly plan\n"
            "• Get a shopping list\n"
            "• Send a new photo or meal idea\n\n"
            "You can also reply with a message like \"Use 1 for Wednesday dinner\" after I suggest meal options."
        )
        if user.language_code == "es":
            welcome = (
                "¡Bienvenido de vuelta 👋\n\n"
                "¿Qué te gustaría hacer hoy?\n"
                "• Crear o ver tu plan semanal\n"
                "• Obtener una lista de compras\n"
                "• Enviar una nueva foto o idea de comida\n\n"
                "También puedes responder con algo como \"Use 1 for Wednesday dinner\" después de que sugiera opciones de comida."
            )
        await update.message.reply_text(welcome, reply_markup=main_menu_markup())
        return ConversationHandler.END
    locale = user.language_code or "en"
    context.user_data["onboarding_locale"] = locale
    context.user_data["onboarding_language"] = locale
    context.user_data["onboarding_age_months"] = 12

    intro = (
        "Hi! I'm your baby feeding assistant 🍼\n\n"
        "I help you:\n"
        "• Turn food ideas into baby-friendly meals\n"
        "• Build weekly meal plans\n"
        "• Create shopping lists\n\n"
        "To get started, how old is your baby in months?\n"
        "(Reply with a number, or send skip to use 12 months)"
    )
    if locale == "es":
        intro = (
            "¡Hola! Soy tu asistente de alimentación infantil 🍼\n\n"
            "Te ayudo a:\n"
            "• Convertir ideas de comida en comidas seguras para bebés\n"
            "• Crear planes semanales de comidas\n"
            "• Hacer listas de compras\n\n"
            "Para empezar, ¿cuántos meses tiene tu bebé?\n"
            "(Responde con un número, o envía skip para usar 12 meses)"
        )
    await update.message.reply_text(intro, reply_markup=main_menu_markup())
    return ONBOARDING_AGE


async def onboarding_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return ConversationHandler.END
    age_months = parse_int_or_default(update.message.text or "", 12)
    context.user_data["onboarding_age_months"] = age_months
    prompt = (
        "Any allergies or foods to avoid?\n"
        "Reply with a comma-separated list, or send none."
    )
    if context.user_data.get("onboarding_language") == "es":
        prompt = (
            "¿Alguna alergia o alimento a evitar?\n"
            "Responde con una lista separada por comas, o envía none."
        )
    await update.message.reply_text(prompt)
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

    ready = (
        "You're all set ✨\n\n"
        "Next, send a food photo, a link, or a meal idea and I'll turn it into baby-friendly options.\n"
        "When you're ready, tap Weekly plan to build next week's schedule."
    )
    if preferred_language == "es":
        ready = (
            "¡Todo listo ✨\n\n"
            "A continuación, envía una foto de comida, un enlace o una idea de comida y la convertiré en opciones seguras para bebés.\n"
            "Cuando estés listo, toca Plan semanal para crear el horario de la próxima semana."
        )
    await update.message.reply_text(ready, reply_markup=main_menu_markup())
    return ConversationHandler.END


async def set_age_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    language = get_user_language(user.id, user.language_code or "en")
    profile = get_profile(user.id)
    if not profile:
        error_msg = "Please run /start first so I can save your baby's profile."
        if language == "es":
            error_msg = "Por favor usa /start primero para guardar el perfil de tu bebé."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    args = context.args or []
    if not args:
        usage = "Use /set_age <months>, for example: /set_age 12"
        if language == "es":
            usage = "Usa /set_age <meses>, por ejemplo: /set_age 12"
        await update.message.reply_text(usage, reply_markup=main_menu_markup())
        return
    age_months = parse_int_or_default(" ".join(args), int(profile.get("age_months") or 12))
    set_profile(
        user.id,
        age_months=age_months,
        allergies=str(profile.get("allergies") or "none"),
        preferred_language=language,
    )
    response = f"Updated age to {age_months} months."
    if language == "es":
        response = f"Edad actualizada a {age_months} meses."
    await update.message.reply_text(response, reply_markup=main_menu_markup())


async def set_allergies_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    language = get_user_language(user.id, user.language_code or "en")
    profile = get_profile(user.id)
    if not profile:
        error_msg = "Please run /start first so I can save your baby's profile."
        if language == "es":
            error_msg = "Por favor usa /start primero para guardar el perfil de tu bebé."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    args = context.args or []
    if not args:
        usage = "Use /set_allergies <comma-separated>, or /set_allergies none"
        if language == "es":
            usage = "Usa /set_allergies <separados por comas>, o /set_allergies none"
        await update.message.reply_text(usage, reply_markup=main_menu_markup())
        return
    allergies = normalize_allergies(" ".join(args))
    set_profile(
        user.id,
        age_months=int(profile.get("age_months") or 12),
        allergies=allergies,
        preferred_language=language,
    )
    response = f"Updated allergies to: {allergies}."
    if language == "es":
        response = f"Alergias actualizadas a: {allergies}."
    await update.message.reply_text(response, reply_markup=main_menu_markup())


async def weekly_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    language = get_user_language(user.id, user.language_code or "en")
    profile = get_profile(user.id)
    if not profile:
        error_msg = "Please run /start first so I can save your baby's profile."
        if language == "es":
            error_msg = "Por favor usa /start primero para guardar el perfil de tu bebé."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    week_start = week_start_for_plans(date.today())
    existing = get_weekly_plan(user.id, week_start=week_start)
    if existing:
        try:
            plan_obj = normalize_plan_dict(json.loads(str(existing["plan_json"])), week_start=week_start)
        except Exception:
            plan_obj = {"days": {}, "raw": str(existing["plan_json"])}
        if plan_has_content(plan_obj):
            week_label = f"Week of {week_start.isoformat()}"
            if language == "es":
                week_label = f"Semana del {week_start.isoformat()}"
            await update.message.reply_text(
                f"📅 {week_label}\n\n{render_weekly_plan(plan_obj, language)}",
                reply_markup=main_menu_markup(),
            )
            return
    inspirations = get_recent_inspirations(user.id, limit=10)
    await update.message.chat.send_action("typing")
    plan_obj = await generate_weekly_plan(profile=profile, inspirations=inspirations, week_start=week_start, language=language, telegram_user_id=user.id)
    if not plan_has_content(plan_obj):
        error_msg = "I couldn't build a reliable weekly plan right now. Please try again in a moment or send a fresh meal idea first."
        if language == "es":
            error_msg = "No pude crear un plan semanal confiable ahora. Por favor intenta de nuevo o envía una nueva idea de comida primero."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    upsert_weekly_plan(user.id, week_start=week_start, plan_json=json.dumps(plan_obj, ensure_ascii=False))
    week_label = f"Week of {week_start.isoformat()}"
    tip = "Tip: after I suggest meal options, reply with \"Use 1 for Wednesday dinner\" to swap a meal."
    if language == "es":
        week_label = f"Semana del {week_start.isoformat()}"
        tip = "Consejo: después de que sugiera opciones de comida, responde con \"Use 1 for Wednesday dinner\" para cambiar una comida."

    # Check if user has enough feedback for the preference note
    stats = get_meal_rating_stats(user.id, week_start)
    preference_note = ""
    if stats and stats.get("total_meals", 0) >= 3:
        if language == "es":
            preference_note = f"\n\nHas calificado {stats['total_meals']} comidas — ¿Quieres que tenga en cuenta tus preferencias en el próximo plan?"
        else:
            preference_note = f"\n\nYou've rated {stats['total_meals']} meals — shall I factor your preferences into next week's plan?"

    await update.message.reply_text(
        f"📅 {week_label}\n\n{render_weekly_plan(plan_obj, language)}\n\n{tip}{preference_note}",
        reply_markup=main_menu_markup(),
    )


async def shopping_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    language = get_user_language(user.id, user.language_code or "en")
    profile = get_profile(user.id)
    if not profile:
        error_msg = "Please run /start first so I can save your baby's profile."
        if language == "es":
            error_msg = "Por favor usa /start primero para guardar el perfil de tu bebé."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    week_start = week_start_for_plans(date.today())
    existing = get_weekly_plan(user.id, week_start=week_start)
    if not existing:
        error_msg = "I need a weekly plan first. Tap Weekly plan and I'll build one for you."
        if language == "es":
            error_msg = "Primero necesito un plan semanal. Toca Plan semanal y yo crearé uno para ti."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    try:
        plan_obj = normalize_plan_dict(json.loads(str(existing["plan_json"])), week_start=week_start)
    except Exception:
        error_msg = "I couldn't read your saved plan. Tap Weekly plan to refresh it."
        if language == "es":
            error_msg = "No pude leer tu plan guardado. Toca Plan semanal para actualizzarlo."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    if not plan_has_content(plan_obj):
        error_msg = "Your saved plan looks incomplete. Tap Weekly plan to rebuild it."
        if language == "es":
            error_msg = "Tu plan guardado parece incompleto. Toca Plan semanal para reconstruirlo."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    await update.message.chat.send_action("typing")
    list_text = await generate_shopping_list(plan_json=plan_obj, language=language, telegram_user_id=user.id)
    await update.message.reply_text(format_shopping_list_message(list_text, language), reply_markup=main_menu_markup())


async def allergen_journal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the allergen introduction journal for the user."""
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    language = get_user_language(user.id, user.language_code or "en")
    profile = get_profile(user.id)
    if not profile:
        error_msg = "Please run /start first so I can save your baby's profile."
        if language == "es":
            error_msg = "Por favor usa /start primero para guardar el perfil de tu bebé."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return

    entries = get_allergen_journal(user.id)
    introduced = get_introduced_allergens(user.id)

    header = "🥜 Allergen Journal" if language == "en" else "🥜 Registro de Alérgenos"
    known_allergens = profile.get("allergies", "") or ""
    known_list = [a.strip().lower() for a in known_allergens.split(",") if a.strip() and a.strip() != "none"]

    lines = [header, "━━━━━━━━━━━━━━━━━━━━", ""]

    if known_list:
        lines.append(f"⚠️ Known allergies: {', '.join(known_list)}")
        lines.append("")

    if introduced:
        lines.append("✅ Introduced allergens:")
        for entry in entries:
            date_str = humanize_timestamp(entry.get("introduced_at", ""))
            allergen = str(entry.get("allergen", "")).capitalize()
            reactions = entry.get("reactions")
            rx_note = f" — Reactions: {reactions}" if reactions else ""
            lines.append(f"• {allergen} ({date_str}){rx_note}")
        lines.append("")
    else:
        no_intro = "No allergens introduced yet." if language == "en" else "Aún no se han introducido alérgenos."
        lines.append(no_intro)
        lines.append("")

    track_list = ", ".join(a.capitalize() for a in ALLERGEN_TRACK_LIST)
    track_note = f"Trackable: {track_list}" if language == "en" else f"Seguibles: {track_list}"
    lines.append(track_note)
    hint = '\nLog with: /introduce <allergen>' if language == "en" else '\nRegistra con: /introduce <alérgeno>'
    lines.append(hint)

    await update.message.reply_text("\n".join(lines).strip(), reply_markup=main_menu_markup())


async def introduce_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log a new allergen introduction via /introduce <allergen> [reactions]."""
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    language = get_user_language(user.id, user.language_code or "en")
    profile = get_profile(user.id)
    if not profile:
        error_msg = "Please run /start first so I can save your baby's profile."
        if language == "es":
            error_msg = "Por favor usa /start primero para guardar el perfil de tu bebé."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return

    args = context.args or []
    if not args:
        usage = "Use /introduce <allergen> [reactions], for example: /introduce peanut or /introduce egg mild rash"
        if language == "es":
            usage = "Usa /introduce <alérgeno> [reacciones], por ejemplo: /introduce maní o /introduce huevo sarpullido leve"
        await update.message.reply_text(usage, reply_markup=main_menu_markup())
        return

    allergen = args[0].strip().lower()
    reactions = " ".join(args[1:]).strip() if len(args) > 1 else None

    # Validate against track list
    if allergen not in ALLERGEN_TRACK_LIST:
        invalid = f"'{allergen}' is not in the tracking list. Trackable allergens: {', '.join(ALLERGEN_TRACK_LIST)}"
        if language == "es":
            invalid = f"'{allergen}' no está en la lista. Alérgenos rastreables: {', '.join(ALLERGEN_TRACK_LIST)}"
        await update.message.reply_text(invalid, reply_markup=main_menu_markup())
        return

    was_new = introduce_allergen(user.id, allergen, reactions)
    allergen_cap = allergen.capitalize()
    now_str = datetime.now(UTC).strftime("%b %d")

    if was_new:
        msg = f"✅ Logged first introduction of {allergen_cap} on {now_str}."
        note = "\n\n💡 Tip: Serve a small amount and wait 3-4 days before introducing another new allergen."
        if language == "es":
            msg = f"✅ Registrada primera introducción de {allergen_cap} el {now_str}."
            note = "\n\n💡 Consejo: Sirve una pequeña cantidad y espera 3-4 días antes de introducir otro alérgeno nuevo."
        if reactions:
            msg += f" Reactions noted: {reactions}"
    else:
        msg = f"📝 Updated introduction record for {allergen_cap} on {now_str}."
        if reactions:
            msg += f" Reactions noted: {reactions}"

    await update.message.reply_text(msg + note if was_new else msg, reply_markup=main_menu_markup())


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    language = get_user_language(user.id, user.language_code or "en")
    plans = get_recent_plans(user.id, limit=3)
    inspirations = get_recent_inspirations(user.id, limit=5)
    await update.message.reply_text(render_history_message(plans, inspirations, language), reply_markup=main_menu_markup())


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
    slot = " ".join((slot or "").strip().lower().split())
    mapping = {
        "breakfast": "breakfast",
        "snack1": "snack1",
        "snack 1": "snack1",
        "morning snack": "snack1",
        "snack2": "snack2",
        "snack 2": "snack2",
        "afternoon snack": "snack2",
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
    language = get_user_language(user.id, user.language_code or "en")
    profile = get_profile(user.id)
    if not profile:
        error_msg = "Please run /start first so I can save your baby's profile."
        if language == "es":
            error_msg = "Por favor usa /start primero para guardar el perfil de tu bebé."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    args = context.args or []
    if len(args) < 3:
        usage = (
            "Use /apply <inspiration_id> <day> <slot>, for example: /apply 12 mon dinner.\n"
            "A simpler option is to reply with \"Use 1 for Wednesday dinner\" after I suggest meal ideas."
        )
        if language == "es":
            usage = (
                "Usa /apply <inspiration_id> <día> <comida>, por ejemplo: /apply 12 mon dinner.\n"
                "Una opción más simple es responder con \"Use 1 for Wednesday dinner\" después de que sugiera ideas de comida."
            )
        await update.message.reply_text(usage, reply_markup=main_menu_markup())
        return
    try:
        inspiration_id = int(args[0])
    except Exception:
        error_msg = "I couldn't read that inspiration number."
        if language == "es":
            error_msg = "No pude leer ese número de inspiración."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    day_key = normalize_day(args[1])
    slot_key = normalize_slot(args[2])
    if not day_key or not slot_key:
        error_msg = "Please use a day from Monday to Sunday and a slot like breakfast, lunch, dinner, snack1, or snack2."
        if language == "es":
            error_msg = "Por favor usa un día de lunes a domingo y una comida como breakfast, lunch, dinner, snack1, o snack2."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    inspiration = get_inspiration(user.id, inspiration_id)
    if not inspiration:
        error_msg = "I couldn't find that saved inspiration."
        if language == "es":
            error_msg = "No pude encontrar esa inspiración guardada."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    week_start = week_start_for_plans(date.today())
    existing = get_weekly_plan(user.id, week_start=week_start)
    if not existing:
        error_msg = "I need a weekly plan first. Tap Weekly plan and I'll build one for you."
        if language == "es":
            error_msg = "Primero necesito un plan semanal. Toca Plan semanal y yo crearé uno para ti."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    try:
        plan_obj = normalize_plan_dict(json.loads(str(existing["plan_json"])), week_start=week_start)
    except Exception:
        error_msg = "I couldn't read your saved plan. Tap Weekly plan to refresh it."
        if language == "es":
            error_msg = "No pude leer tu plan guardado. Toca Plan semanal para actualizzarlo."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    await update.message.chat.send_action("typing")
    new_meal = await generate_meal_for_slot(
        profile=profile,
        inspiration_summary=str(inspiration.get("summary") or ""),
        selected_adaptation=get_adaptation_by_index(inspiration, 1),
        day_key=day_key,
        slot_key=slot_key,
        language=language,
    )
    normalized_meal = normalize_meal_dict(new_meal)
    if not normalized_meal:
        error_msg = "I couldn't safely update that meal right now. Please try again with a different inspiration."
        if language == "es":
            error_msg = "No pude actualizar esa comida de manera segura ahora. Por favor intenta de nuevo con una inspiración diferente."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    plan_obj.setdefault("days", {}).setdefault(day_key, {})[slot_key] = normalized_meal
    upsert_weekly_plan(user.id, week_start=week_start, plan_json=json.dumps(plan_obj, ensure_ascii=False))
    await update.message.reply_text(
        f"{render_single_meal(day_key, slot_key, normalized_meal, language)}\n\n{render_weekly_plan(plan_obj, language)}",
        reply_markup=main_menu_markup(),
    )


async def rate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    language = get_user_language(user.id, user.language_code or "en")
    profile = get_profile(user.id)
    if not profile:
        error_msg = "Please run /start first so I can save your baby's profile."
        if language == "es":
            error_msg = "Por favor usa /start primero para guardar el perfil de tu bebé."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    args = context.args or []
    if len(args) < 2:
        usage = "Use /rate <meal_id> <up|down|0> [comment], for example: /rate tue.lunch up loved it"
        if language == "es":
            usage = "Usa /rate <meal_id> <up|down|0> [comentario], por ejemplo: /rate tue.lunch up me encantó"
        await update.message.reply_text(usage, reply_markup=main_menu_markup())
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
        error_msg = "Please rate with up, down, or 0."
        if language == "es":
            error_msg = "Por favor califica con up, down, o 0."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    comment = " ".join(args[2:]).strip() if len(args) > 2 else None
    week_start = week_start_for_plans(date.today())
    existing = get_weekly_plan(user.id, week_start=week_start)
    if not existing:
        error_msg = "I need a weekly plan first. Tap Weekly plan and I'll build one for you."
        if language == "es":
            error_msg = "Primero necesito un plan semanal. Toca Plan semanal y yo crearé uno para ti."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return
    weekly_plan_id = int(existing["id"])
    now = datetime.now(UTC).isoformat()
    with _db_conn() as conn:
        conn.execute(
            """
            INSERT INTO feedback (telegram_user_id, weekly_plan_id, meal_id, rating, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user.id, weekly_plan_id, meal_id, rating, comment, now),
        )
    response = "Saved your feedback. Thank you!"
    if language == "es":
        response = "¡Guardado tu feedback. Gracias!"
    await update.message.reply_text(response, reply_markup=main_menu_markup())


async def regenerate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Regenerate a single meal slot: /regenerate <day> <slot> e.g. /regenerate wed lunch"""
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return
    upsert_user(user.id, user.language_code)
    language = get_user_language(user.id, user.language_code or "en")
    profile = get_profile(user.id)
    if not profile:
        error_msg = "Please run /start first so I can save your baby's profile."
        if language == "es":
            error_msg = "Por favor usa /start primero para guardar el perfil de tu bebé."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return

    args = context.args or []
    if len(args) < 2:
        usage = "Use /regenerate <day> <slot>, for example: /regenerate wed lunch"
        if language == "es":
            usage = "Usa /regenerate <día> <comida>, por ejemplo: /regenerate wed lunch"
        await update.message.reply_text(usage, reply_markup=main_menu_markup())
        return

    day_key = normalize_day(args[0])
    slot_key = normalize_slot(args[1])
    if not day_key or not slot_key:
        error_msg = "Please use a day (Mon-Sun) and slot (breakfast, lunch, dinner, snack1, snack2)."
        if language == "es":
            error_msg = "Por favor usa un día (Mon-Sun) y comida (breakfast, lunch, dinner, snack1, snack2)."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return

    week_start = week_start_for_plans(date.today())
    existing = get_weekly_plan(user.id, week_start=week_start)
    if not existing:
        error_msg = "I need a weekly plan first. Tap Weekly plan to build one."
        if language == "es":
            error_msg = "Primero necesito un plan semanal. Toca Plan semanal para crear uno."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return

    try:
        plan_obj = normalize_plan_dict(json.loads(str(existing["plan_json"])), week_start=week_start)
    except Exception:
        error_msg = "I couldn't read your current plan. Tap Weekly plan to refresh it."
        if language == "es":
            error_msg = "No pude leer tu plan actual. Toca Plan semanal para actualizzarlo."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return

    await update.message.chat.send_action("typing")

    # Get inspiration context from the most recent inspiration
    inspiration = get_latest_inspiration(user.id)
    if inspiration:
        inspiration_summary = str(inspiration.get("summary") or "")
        adaptation = get_adaptation_by_index(inspiration, 1)
    else:
        inspiration_summary = ""
        adaptation = ""

    new_meal = await generate_meal_for_slot(
        profile=profile,
        inspiration_summary=inspiration_summary or "A simple nutritious baby meal",
        selected_adaptation=adaptation,
        day_key=day_key,
        slot_key=slot_key,
        language=language,
    )
    normalized_meal = normalize_meal_dict(new_meal)
    if not normalized_meal:
        error_msg = "I couldn't safely regenerate that meal right now. Please try again."
        if language == "es":
            error_msg = "No pude regenerar esa comida de manera segura ahora. Intenta de nuevo."
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())
        return

    # Show the new meal with accept/revert inline keyboard
    old_meal = (plan_obj.get("days") or {}).get(day_key, {}).get(slot_key)
    plan_obj.setdefault("days", {}).setdefault(day_key, {})[slot_key] = normalized_meal

    day_label = DAY_LABELS.get(day_key, day_key.title())
    slot_label = SLOT_LABELS.get(slot_key, slot_key).lower()

    new_text = f"🔄 New suggestion for {day_label} {slot_label}:\n\n{render_meal_card(normalized_meal, slot_key, language)}"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Accept", callback_data=f"regen_accept:{day_key}:{slot_key}"),
            InlineKeyboardButton("↩️ Revert", callback_data=f"regen_revert:{day_key}:{slot_key}"),
        ]
    ])

    await update.message.reply_text(new_text, reply_markup=keyboard)


async def handle_regen_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle accept/revert for regenerate suggestions."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    user = query.from_user
    if not user:
        return

    language = get_user_language(user.id, user.language_code or "en")
    data = query.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        return

    action = parts[0]
    day_key = parts[1]
    slot_key = parts[2]

    week_start = week_start_for_plans(date.today())
    existing = get_weekly_plan(user.id, week_start=week_start)
    if not existing:
        await query.answer("Plan not found.", show_alert=True)
        return

    try:
        plan_obj = normalize_plan_dict(json.loads(str(existing["plan_json"])), week_start=week_start)
    except Exception:
        await query.answer("Couldn't read plan.", show_alert=True)
        return

    if action == "regen_revert":
        await query.answer("Reverted to original meal.")
        await query.edit_message_reply_markup(reply_markup=None)
        return

    # regen_accept — save the new meal
    await query.edit_message_reply_markup(reply_markup=None)
    upsert_weekly_plan(user.id, week_start=week_start, plan_json=json.dumps(plan_obj, ensure_ascii=False))
    await context.bot.send_message(
        query.message.chat_id,
        f"✅ Accepted! {day_key.title()} {slot_key} updated.\n\n{render_weekly_plan(plan_obj, language)}",
        reply_markup=main_menu_markup(),
    )


def main() -> None:
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
    application.add_handler(CommandHandler("regenerate", regenerate_command))
    application.add_handler(CommandHandler("introduce", introduce_command))

    # Inline keyboard callback handlers (must be added before generic text handler)
    application.add_handler(CallbackQueryHandler(handle_apply_callback, pattern=r"^(opt|selday|apply|back):"))
    application.add_handler(CallbackQueryHandler(handle_regen_callback, pattern=r"^regen_"))

    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot is running! Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()