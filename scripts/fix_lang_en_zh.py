#!/usr/bin/env python3
"""Systematically remove Spanish/German, keep EN+ZH. In-place edit."""
import re, sys

path = "/home/deploy/baby-feeding-bot/baby_feeding_bot.py"
with open(path, encoding="utf-8") as f:
    content = f.read()

orig = content

# ── 1. Swap language checks: es → zh ─────────────────────────────────────────
# All if/elif language==es, !=es, checks → zh
# and es string dict-keys → zh (for the dict lookups we kept)
content = re.sub(r'language == "es"(?!\w)', 'language == "zh"', content)
content = re.sub(r'language != "es"(?!\w)', 'language != "zh"', content)
content = re.sub(r'locale == "es"', 'locale == "zh"', content)
content = re.sub(r'preferred_language == "es"', 'preferred_language == "zh"', content)
content = re.sub(r'user\.language_code == "es"', 'user.language_code == "zh"', content)
content = re.sub(r'"onboarding_language"\) == "es"', '"onboarding_language") == "zh"', content)

# ── 2. Shopping list header (EN/ES only) ────────────────────────────────────
content = content.replace(
    '"🛒 Shopping List" if language == "en" else "🛒 Lista de Compras"',
    '"🛒 Shopping List" if language == "en" else "🛒 购物清单"'
)

# ── 3. render_weekly_plan — swap EN/ES tip (line ~991) ────────────────────
content = content.replace(
    '"💡 Tip: Serve iron-rich foods with vitamin C (e.g., strawberry with fortified cereal) to boost absorption."',
    '"💡 Tip: Serve iron-rich foods with vitamin C (e.g., strawberry with fortified cereal) to boost absorption."'
)
# The ES tip was already handled in step 4 of previous edits (but let's catch any stragglers)
content = re.sub(
    r'if language == "zh":\s+tip = "💡 Tip.*?"\s+else:\s+tip = "💡 Tip.*?"',
    'tip = "💡 Tip: Serve iron-rich foods with vitamin C (e.g., strawberry with fortified cereal) to boost absorption."',
    content
)

# ── 4. Slot label — the SLOT_LABELS has es values in render_meal_card ────────
# These are in: "Morning snack" if language == "en" else "Mini-merienda" etc
# Since we're removing es, we need to swap these to zh or just remove the Spanish
content = re.sub(
    r'"Breakfast" if language == "en" else "[^"]*"',
    '"Breakfast" if language == "en" else "早餐"',
    content
)
content = re.sub(
    r'"Morning snack" if language == "en" else "[^"]*"',
    '"Morning snack" if language == "en" else "早间点心"',
    content
)
content = re.sub(
    r'"Lunch" if language == "en" else "[^"]*"',
    '"Lunch" if language == "en" else "午餐"',
    content
)
content = re.sub(
    r'"Afternoon snack" if language == "en" else "[^"]*"',
    '"Afternoon snack" if language == "en" else "下午点心"',
    content
)
content = re.sub(
    r'"Dinner" if language == "en" else "[^"]*"',
    '"Dinner" if language == "en" else "晚餐"',
    content
)

# ── 5. render_meal_card return tip ───────────────────────────────────────────
# "Try offering a variety of colors and textures to make meals more appealing."
# The ES version was: "Prueba ofrecer una variedad de colores y texturas."
content = content.replace(
    '"Try offering a variety of colors and textures to make meals more appealing."',
    '"Try offering a variety of colors and textures to make meals more appealing."'
)

# ── 6. render_adaptation_card option labels ─────────────────────────────────
# Option 1 / Opción 1 → Option 1 / 选项 1
content = content.replace(
    'f"Option {index}" if language == "en" else f"Opción {index}"',
    'f"Option {index}" if language == "en" else f"选项 {index}"'
)

# ── 7. Render history message headers ───────────────────────────────────────
content = content.replace('"📚 Recent Plans" if language == "en" else "📚 Planes Recientes"',
                          '"📚 Recent Plans" if language == "en" else "📚 最近的计划"')
content = content.replace('"💡 Recent Inspirations" if language == "en" else "💡 Inspiraciones Recientes"',
                          '"💡 Recent Inspirations" if language == "en" else "💡 最近的灵感"')

# ── 8. Save plan messages ───────────────────────────────────────────────────
content = content.replace(
    '"\U0001f4be Plan saved!" if language == "en" else "\U0001f4be \u00a1Plan guardado!"',
    '"\U0001f4be Plan saved!" if language == "en" else "\U0001f4be 计划已保存！"'
)
content = content.replace(
    '"Plan already saved"',
    '"计划已保存"'
)

# ── 9. Nutrition summary header ─────────────────────────────────────────────
content = content.replace(
    '"📊 Nutrition Summary" if language == "en" else "📊 Resumen Nutricional"',
    '"📊 Nutrition Summary" if language == "en" else "📊 营养摘要"'
)

# ── 10. Toggle lang messages ────────────────────────────────────────────────
content = content.replace(
    '"Language set to English." if new_lang == "en" else "Idioma configurado a Español."',
    '"Language set to English." if new_lang == "en" else "语言已设置为中文。"'
)

# ── 11. Stats ───────────────────────────────────────────────────────────────
content = re.sub(
    r'"Here are your meal stats."\s+if language == "en"\s+else\s+"Aquí tienes tus estadísticas de comida."',
    '"Here are your meal stats." if language == "en" else "这是您的餐饮统计。"',
    content
)
content = re.sub(
    r'"Not enough data yet."\s+if language == "en"\s+else\s+"No hay suficientes datos todavía."',
    '"Not enough data yet." if language == "en" else "暂无足够数据。"',
    content
)

# ── 12. Allergen journal ────────────────────────────────────────────────────
content = content.replace(
    '"🥜 Allergen journal" if language == "en" else "🥜 Registro de alergias"',
    '"🥜 Allergen journal" if language == "en" else "🥜 过敏记录"'
)

# ── 13. Cancel messages ─────────────────────────────────────────────────────
content = re.sub(
    r'"Operation cancelled."\s+if language == "en"\s+else\s+"Cancelado."',
    '"Operation cancelled." if language == "en" else "操作已取消。"',
    content
)

# ── 14. Back to week button (in day detail view) — already updated to ZH) ──
# Verify no remaining ES refs in back_labels dict
content = content.replace(
    '"← Back to week" if language == "en" else "← Volver a la semana"',
    '"← Back to week" if language == "en" else "← 返回周视图"'
)

# ── 15. Error messages ───────────────────────────────────────────────────────
content = content.replace(
    '"No plan found. Use /weekly_plan to build one."',
    '"No plan found. Use /weekly_plan to build one."'
)
content = content.replace(
    '"Couldn\'t read your plan. Try /weekly_plan to rebuild it."',
    '"Couldn\'t read your plan. Try /weekly_plan to rebuild it."'
)

# ── 16. View week button after save ─────────────────────────────────────────
content = content.replace(
    '"\U0001f4c5 View week"',
    '"\U0001f4c5 查看计划"'
)

# ── 17. Count remaining Spanish/German references ───────────────────────────
remaining_es = len(re.findall(r'"es"|\'es\'', content))
remaining_de = len(re.findall(r'"de"|\'de\'', content))
# Filter out things that are NOT language codes (like "days" containing "es")
es_in_strings = remaining_es
de_in_strings = remaining_de
print(f"Remaining 'es' refs: {remaining_es}")
print(f"Remaining 'de' refs: {remaining_de}")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("File updated.")
print(f"Chars changed: {len(content) - len(orig)}")
