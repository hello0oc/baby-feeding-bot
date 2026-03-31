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
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any, Optional, List

import httpx
from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_PLACES_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_FALLBACK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite")
DB_PATH = os.environ.get("BABY_FEEDING_DB_PATH", "baby_feeding.sqlite3")
RETENTION_INSPIRATIONS_DAYS = int(os.environ.get("BABY_FEEDING_RETENTION_INSPIRATIONS_DAYS", "90"))
RETENTION_FEEDBACK_DAYS = int(os.environ.get("BABY_FEEDING_RETENTION_FEEDBACK_DAYS", "90"))
RETENTION_PLANS_DAYS = int(os.environ.get("BABY_FEEDING_RETENTION_PLANS_DAYS", "365"))

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("BABY_FEEDING_BOT_TOKEN environment variable not set")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set (also accepts GOOGLE_PLACES_API_KEY)")

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

MAIN_MENU_ROWS = [
    ["📅 Weekly plan", "🛒 Shopping list"],
    ["📚 History", "👶 Update age"],
    ["🥜 Update allergies", "❓ Help"],
]
MENU_TO_ACTION = {
    "📅 Weekly plan": "weekly_plan",
    "🛒 Shopping list": "shopping_list",
    "📚 History": "history",
    "👶 Update age": "update_age",
    "🥜 Update allergies": "update_allergies",
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
    if not lines:
        option_label = "Option 1" if language == "en" else "Opción 1"
        return f"{option_label}\n• A gentle baby-friendly idea is ready."
    title = lines[0]
    body = [f"  {line}" for line in lines[1:5]]
    option_label = f"Option {index}" if language == "en" else f"Opción {index}"
    return f"━━━━━━━━━━━━━━━━━━━━\n{option_label} — {title}\n" + "\n".join(body)


def render_inspiration_message(summary: str, adaptations: List[str], language: str = "en") -> str:
    intro = "Here's what I found:" if language == "en" else "Esto es lo que encontré:"
    option_prompt = "Reply with \"Use 1 for [Day] [Meal]\"" if language == "en" else 'Responde con "Use 1 for [Día] [Comida]"'
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
        f"Next step: {option_prompt}",
        "Example: Use 1 for Wednesday dinner",
    ]
    return "\n".join(section for section in sections if section is not None).strip()


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


async def gemini_generate(
    parts: List[dict[str, Any]],
    *,
    temperature: float = 0.4,
    max_tokens: int = 2048,
    model: str = None,
) -> str:
    primary = model or GEMINI_MODEL
    fallback = GEMINI_FALLBACK_MODEL
    friendly_error = "Sorry, I had trouble generating a response right now."

    for attempt_model in [primary, fallback]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{attempt_model}:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        try:
            async with httpx.AsyncClient() as http_client:
                response = await http_client.post(url, json=payload, timeout=45.0)
                if response.status_code != 200:
                    logger.error("Gemini API error for %s: %s", attempt_model, response.status_code)
                    continue
                result = response.json()
                candidates = result.get("candidates") or []
                if not candidates:
                    logger.error("Gemini API returned no candidates for %s", attempt_model)
                    continue
                content = (candidates[0].get("content") or {}).get("parts") or []
                if not content:
                    logger.error("Gemini API returned empty content for %s", attempt_model)
                    continue
                text = str(content[0].get("text") or "").strip()
                if not text:
                    logger.error("Gemini API returned blank text for %s", attempt_model)
                    continue
                return text
        except Exception as e:
            logger.error("Gemini API exception for %s: %s", attempt_model, e)
            continue

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
        if language == "es":
            prompt = (
                "Describe the food shown and extract a short theme I can use as a meal inspiration.\n"
                "Return 2-3 bullet points.\n"
                f"Respond in language: Spanish"
            )
        else:
            prompt = (
                "Describe the food shown and extract a short theme I can use as a meal inspiration.\n"
                "Return 2-3 bullet points.\n"
                f"Respond in language: English"
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


async def generate_two_adaptations(*, inspiration: str, profile: Optional[dict[str, Any]], language: str) -> List[str]:
    system = MEAL_SYSTEM_PROMPT
    if language == "es":
        system = system.replace("12-month-old", "de 12 meses").replace("You are a helpful assistant", "Eres un asistente útil")

    prompt = (
        f"{system}\n\n"
        "Task: Based on the inspiration, propose exactly 2 baby-safe meal adaptations.\n"
        "Each adaptation must be 3-5 lines:\n"
        "- Meal name\n"
        "- Key ingredients\n"
        "- Quick prep\n"
        "- Safety note\n\n"
        f"Constraints:\n{profile_constraints_text(profile)}\n\n"
        f"Inspiration:\n{inspiration}\n\n"
        f"Respond in language: {'Spanish' if language == 'es' else 'English'}"
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
    adaptations: List[str],
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
) -> dict[str, Any]:
    inspiration_text = "\n".join([f"- {i.get('summary', '')}".strip() for i in inspirations if i.get("summary")]) or "none"
    system = MEAL_SYSTEM_PROMPT
    if language == "es":
        system = system.replace("12-month-old", "de 12 meses").replace("You are a helpful assistant", "Eres un asistente útil")

    prompt = (
        f"{system}\n\n"
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
        f"Respond in language: {'Spanish' if language == 'es' else 'English'}"
    )
    text = await gemini_generate([{"text": prompt}], temperature=0.5, max_tokens=2500)
    parsed = parse_json_object(text)
    if not parsed:
        return {"week_start_date": week_start.isoformat(), "days": {}, "raw": text, "error": "parse_failed"}
    normalized = normalize_plan_dict(parsed, week_start=week_start)
    if plan_has_content(normalized):
        return normalized
    normalized["raw"] = text
    normalized["error"] = "empty_plan"
    return normalized


async def generate_shopping_list(*, plan_json: dict[str, Any], language: str) -> str:
    prompt = (
        "Create a consolidated shopping list grouped by category (produce, protein, dairy, pantry, other).\n"
        "Avoid adding salt/sugar items. Keep it concise.\n\n"
        f"Plan JSON:\n{json.dumps(plan_json, ensure_ascii=False)}\n\n"
        f"Respond in language: {'Spanish' if language == 'es' else 'English'}"
    )
    return await gemini_generate([{"text": prompt}], temperature=0.2, max_tokens=1200)


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
        system = system.replace("12-month-old", "de 12 meses").replace("You are a helpful assistant", "Eres un asistente útil")

    prompt = (
        f"{system}\n\n"
        "Create a single meal for the specified day+slot, inspired by the inspiration.\n"
        "Return ONLY valid JSON with keys: title, ingredients (array), quick_prep, safety_note, tags (array).\n\n"
        f"Constraints:\n{profile_constraints_text(profile)}\n\n"
        f"Day: {day_key}\nSlot: {slot_key}\n"
        f"Inspiration:\n{inspiration_summary}\n\n"
        f"Preferred adaptation direction:\n{selected_adaptation or 'Use the best fit for this slot.'}\n\n"
        f"Respond in language: {'Spanish' if language == 'es' else 'English'}"
    )
    text = await gemini_generate([{"text": prompt}], temperature=0.45, max_tokens=900)
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
        await update.message.reply_text(
            render_inspiration_message(inspiration_summary, adaptations, language),
            reply_markup=main_menu_markup(),
        )
    except Exception as e:
        logger.error("Error handling photo: %s", e)
        error_msg = (
            "Sorry, I couldn't process that image. Please try another photo or send a text idea instead."
            if language == "en"
            else "Lo siento, no pude procesar esa imagen. Prueba con otra foto o envía una idea de comida."
        )
        await update.message.reply_text(error_msg, reply_markup=main_menu_markup())


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
        inspiration_summary = await gemini_generate([{"text": summary_prompt}], temperature=0.3, max_tokens=400)
        adaptations = await generate_two_adaptations(inspiration=inspiration_summary, profile=profile, language=language)
        inspiration_id = store_inspiration(
            user.id,
            kind="link",
            source_url=url,
            summary=inspiration_summary,
            adaptations=adaptations,
        )
        context.user_data["last_inspiration_id"] = inspiration_id
        await update.message.reply_text(
            render_inspiration_message(inspiration_summary, adaptations, language),
            reply_markup=main_menu_markup(),
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
    context.user_data["last_inspiration_id"] = inspiration_id
    await update.message.reply_text(
        render_inspiration_message(inspiration_summary, adaptations, language),
        reply_markup=main_menu_markup(),
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
    plan_obj = await generate_weekly_plan(profile=profile, inspirations=inspirations, week_start=week_start, language=language)
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
    await update.message.reply_text(
        f"📅 {week_label}\n\n{render_weekly_plan(plan_obj, language)}\n\n{tip}",
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
    list_text = await generate_shopping_list(plan_json=plan_obj, language=language)
    await update.message.reply_text(format_shopping_list_message(list_text, language), reply_markup=main_menu_markup())


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
    now = datetime.utcnow().isoformat()
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

    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot is running! Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()