#!/usr/bin/env python3
"""Apply all fixes to baby_feeding_bot.py in one clean pass."""
import re

path = "/home/deploy/baby-feeding-bot/baby_feeding_bot.py"
with open(path, encoding="utf-8") as f:
    content = f.read()

# ─── FIX 1: meal.get("name") → meal.get("title") in digest ─────────────────
content = content.replace(
    'name = meal.get("name", "")',
    'name = meal.get("title", "")'
)

# ─── FIX 2: LLM prompt language fallbacks (Spanish → Chinese) ────────────────
content = content.replace(
    'Respond in language: {"Spanish" if language == "es" else "English"}',
    'Respond in language: {"Chinese" if language == "zh" else "English"}'
)

# ─── FIX 3: System prompt corruption (remove "Eres un asistente útil" blocks) ───
# Remove if language=="zh": system = system.replace(...)  (these are orphaned empty blocks)
# Pattern: if language == "zh":\n        system = system.replace(...)
content = re.sub(
    r'\n    if language == "zh":\n        system = system\.replace\([^)]+\)',
    '',
    content
)

# ─── FIX 4: lang = "Spanish" if zh → lang = "Chinese" if zh ────────────────
content = content.replace(
    'lang = "Spanish" if language == "zh" else "English"',
    'lang = "Chinese" if language == "zh" else "English"'
)

# ─── FIX 5: Shopping list fallback message (Spanish → Chinese) ────────────────
content = content.replace(
    '"No pude crear una lista de compras. Inténtalo de nuevo después de generar un plan semanal."',
    '"暂无法生成购物清单。请先创建每周计划后再试。"'
)

# ─── FIX 6: MAIN_MENU language toggle → Lang + dynamic state ─────────────────
content = content.replace(
    'def main_menu_markup() -> ReplyKeyboardMarkup:\n    return ReplyKeyboardMarkup(MAIN_MENU_ROWS, resize_keyboard=True)',
    'def main_menu_markup(language: Optional[str] = None, telegram_user_id: Optional[int] = None) -> ReplyKeyboardMarkup:\n'
    '    if language is None and telegram_user_id is not None:\n'
    '        language = get_user_language(telegram_user_id, "en")\n'
    '    if language is None:\n'
    '        language = "en"\n'
    '    lang_label = {"en": "🌐 中文", "zh": "🌐 English"}.get(language, "🌐 Lang")\n'
    '    rows: List[List[str]] = [\n'
    '        ["📆 Today", "📅 Weekly plan"],\n'
    '        ["🛒 Shopping list", "📚 History"],\n'
    '        ["👶 Update age", "🥜 Update allergies"],\n'
    '        ["🥜 Allergen journal", "❓ Help"],\n'
    '        [lang_label, "👤 Profile"],\n'
    '    ]\n'
    '    return ReplyKeyboardMarkup(rows, resize_keyboard=True)'
)

# ─── FIX 7: MENU_TO_ACTION language key ──────────────────────────────────────
content = content.replace('"🌐 EN/ES": "toggle_lang"', '"🌐 Lang": "toggle_lang"')

# ─── FIX 8: Shopping list renderer - user-friendly format ─────────────────────
# Replace entire _render_shopping_list_from_json function
old_sl = '''def _render_shopping_list_from_json(raw: str, language: str = "en") -> str:
    """
    Parse LLM JSON response and render as formatted shopping list.
    Falls back to stripped text if JSON parsing fails.
    """
    header = "🛒 Shopping List" if language == "en" else "🛒 Lista de Compras"
    try:
        cleaned = re.sub(r"```(?:json)?\\s*", "", raw.strip()).strip()
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("Not a dict")
    except Exception:
        fallback = re.sub(r"```", "", raw).strip()
        return f"{header}\\n━━━━━━━━━━━━━━━━━━━━\\n\\n{fallback}"

    CATEGORY_EMOJI = {
        "produce": "🥦 Produce",
        "protein": "🥩 Protein",
        "dairy": "🧀 Dairy",
        "pantry": "🫙 Pantry",
        "other": "📦 Other",
    }
    all_items = []
    lines = [header, "━━━━━━━━━━━━━━━━━━━━", ""]
    for key, label in CATEGORY_EMOJI.items():
        items = data.get(key, [])
        if not items:
            continue
        if isinstance(items, list):
            text = " | ".join(str(i) for i in items)
        else:
            text = str(items)
        lines.append(f"{label}")
        lines.append(f"  {text}")
        all_items.extend(items)

    if not all_items:
        fallback = re.sub(r"```", "", raw).strip()
        return f"{header}\\n━━━━━━━━━━━━━━━━━━━━\\n\\n{fallback}"

    return "\\n".join(lines)'''

new_sl = '''def _render_shopping_list_from_json(raw: str, language: str = "en") -> str:
    """
    Parse LLM JSON response and render as a user-friendly shopping list.
    Falls back to smart text formatting if JSON parsing fails.
    """
    header_map = {
        "en": "🛒 Shopping List",
        "zh": "🛒 购物清单",
    }
    fallback_header_map = {
        "en": "🛒 Shopping List\\n\\nCould not parse — here are the items:",
        "zh": "🛒 购物清单\\n\\n无法解析 — 以下是提取的物品：",
    }
    header = header_map.get(language, header_map["en"])
    fallback_header = fallback_header_map.get(language, fallback_header_map["en"])

    # ── Attempt JSON parse ─────────────────────────────────────────────────────
    try:
        cleaned = re.sub(r"```(?:json)?\\s*", "", raw.strip()).strip()
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("Not a dict")
    except Exception:
        lines_out = [fallback_header, "━━━━━━━━━━━━━━━━━━━━", ""]
        fallback_raw = re.sub(r"```", "", raw).strip()
        raw_lines = [l.strip() for l in fallback_raw.splitlines()
                     if l.strip() and not l.strip().startswith("{")
                     and not l.strip().startswith("}")
                     and "Respond in" not in l]
        if raw_lines:
            for item in raw_lines:
                cleaned_item = re.sub(r"^[\\-\\*\\d\\.\\)\\s]+\\s*", "", item).strip()
                if cleaned_item:
                    lines_out.append(f"  • {cleaned_item}")
        else:
            lines_out.append(f"  {fallback_raw or '(empty)'}")
        return "\\n".join(lines_out)

    # ── JSON parsed: render with checkmark bullets and quantities ──────────────
    CATEGORY_EMOJI = {
        "produce": "🥦 Produce",
        "protein": "🥩 Protein",
        "dairy": "🧀 Dairy",
        "pantry": "🫙 Pantry",
        "other": "📦 Other",
    }
    total_items = 0
    lines_out = [header, "━━━━━━━━━━━━━━━━━━━━", ""]

    for key, label in CATEGORY_EMOJI.items():
        items = data.get(key, [])
        if not items:
            continue
        if isinstance(items, list):
            lines_out.append(label)
            for item in items:
                item_str = str(item).strip()
                if item_str:
                    lines_out.append(f"  ☐ {item_str}")
                    total_items += 1
        elif isinstance(items, str):
            lines_out.append(label)
            lines_out.append(f"  ☐ {items}")
            total_items += 1

    if total_items == 0:
        return (header + "\\n\\n" + (cleaned or "(empty)")).replace(header, fallback_header)

    count_map = {"en": f"Total: {total_items} items", "zh": f"共 {total_items} 项"}
    count_label = count_map.get(language, count_map["en"])
    lines_out.extend(["", f"✅ {count_label}"])
    return "\\n".join(lines_out)'''

if old_sl in content:
    content = content.replace(old_sl, new_sl)
    print("  ✅ Shopping list renderer updated")
else:
    print("  ❌ Shopping list renderer not found (may already be updated)")

# ─── FIX 9: Shopping list generation prompt - add quantity guidance ─────────────
# Fix literal \n bug in prompt and add portion guidance
old_prompt = (
    '"Given the ingredients below (already deduplicated), create a clean shopping list.\\n"'
    '"Group items into exactly these 5 categories:\\n"'
    '"🥦 Produce  🥩 Protein  🧀 Dairy  🫙 Pantry  📦 Other\\n\\n"'
    '"Rules:\\n"'
    '"- Use the quantities provided (e.g., 3× carrots). If no quantity is given, list the item once.\\n"'
    '"- Skip salt, sugar, and seasoning items.\\n"'
    '"- Keep each category concise (max 8 items per category).\\n"'
    '"- Respond ONLY with valid JSON in this exact structure (no markdown, no explanation):\\n"'
    '\'{"produce": ["item1", "item2"], "protein": [], "dairy": [], "pantry": [], "other": []}\\n\\n\''
)
new_prompt = (
    '"Given the ingredients below (already deduplicated), create a clean shopping list.\\n"'
    '"Group items into exactly these 5 categories:\\n"'
    '"🥦 Produce  🥩 Protein  🧀 Dairy  🫙 Pantry  📦 Other\\n\\n"'
    '"Rules:\\n"'
    '"- Include quantities where given (e.g., 150g carrots, ½ avocado). '
    'For items without quantity, add a typical baby portion amount.\\n"'
    '"- Skip salt, sugar, and seasonings.\\n"'
    '"- Keep each category concise (max 8 items).\\n"'
    '"- Respond ONLY with valid JSON in this exact structure (no markdown, no explanation):\\n"'
    '\'{"produce": ["150g carrots", "½ avocado"], "protein": ["100g chicken"], "dairy": [], "pantry": [], "other": []}\\n\\n\''
)
if old_prompt in content:
    content = content.replace(old_prompt, new_prompt)
    print("  ✅ Shopping list prompt updated (quantity guidance)")
else:
    print("  ❌ Shopping list prompt not found")

# ─── FIX 10: Welcome-back message (returning user, zh branch) ─────────────────
old_wb = (
    '"¡Bienvenido de vuelta 👋\\n\\n"'
    '"¿Qué te gustaría hacer hoy?\\n"'
    '"• Crear o ver tu plan semanal\\n"'
    '"• Obtener una lista de compras\\n"'
    '"• Enviar una nueva foto o idea de comida\\n\\n"'
    '"También puedes responder con algo como \\"Use 1 for Wednesday dinner\\" después de que sugiera opciones de comida."'
)
new_wb = (
    '"欢迎回来 👋\\n\\n"'
    '"今天想做什么？\\n"'
    '"• 创建或查看每周计划\\n"'
    '"• 获取购物清单\\n"'
    '"• 发送新的食物照片或餐饮想法\\n\\n"'
    '"在我建议餐食选项后，您也可以回复如"选择1作为周三晚餐"来添加餐食。"'
)
if old_wb in content:
    content = content.replace(old_wb, new_wb)
    print("  ✅ Welcome-back message (zh) updated")
else:
    print("  ❌ Welcome-back message not found")

# ─── FIX 11: Onboarding intro (zh locale) ─────────────────────────────────────
old_oi = (
    '"¡Hola! Soy tu asistente de alimentación infantil 🍼\\n\\n"'
    '"Te ayudo a:\\n"'
    '"• Convertir ideas de comida en opciones seguras para bebés\\n"'
    '"• Crear planes semanales de comidas\\n"'
    '"• Hacer listas de compras\\n\\n"'
    '"Para empezar, ¿cuántos meses tiene tu bebé?\\n"'
    '"(Responde con un número, o envía skip para usar 12 meses)"'
)
new_oi = (
    '"你好！我是您的宝宝喂养助手 🍼\\n\\n"'
    '"我可以帮助您：\\n"'
    '"• 将餐饮想法转化为宝宝安全的餐食\\n"'
    '"• 创建每周饮食计划\\n"'
    '"• 生成购物清单\\n\\n"'
    '"首先，您的宝宝多大（按月计算）？\\n"'
    '"（回复数字，或发送skip使用12个月默认值）"'
)
if old_oi in content:
    content = content.replace(old_oi, new_oi)
    print("  ✅ Onboarding intro (zh) updated")
else:
    print("  ❌ Onboarding intro not found")

# ─── FIX 12: Onboarding allergies step (zh) ────────────────────────────────────
old_oa = (
    '"¿Alguna alergia o alimento a evitar?\\n"'
    '"Responde con una lista separada por comas, o envía none."'
)
new_oa = (
    '"您的宝宝有过敏或需要避免的食物吗？\\n"'
    '"请以逗号分隔回复，或发送none表示无过敏。"'
)
if old_oa in content:
    content = content.replace(old_oa, new_oa)
    print("  ✅ Onboarding allergies (zh) updated")
else:
    print("  ❌ Onboarding allergies not found")

# ─── FIX 13: Onboarding ready (zh) ────────────────────────────────────────────
old_or = (
    '"¡Todo listo ✨\\n\\n"'
    '"A continuación, envía una foto de comida, un enlace o una idea de comida y la convertiré en opciones seguras para bebés.\\n"'
    '"Cuando estés listo, toca Plan semanal para crear el horario de la próxima semana."'
)
new_or = (
    '"一切就绪 ✨\\n\\n"'
    '"现在，发送食物照片、链接或餐饮想法，我会将其转化为适合宝宝的安全选项。\\n"'
    '"准备就绪后，点击"每周计划"来创建下周的饮食安排。"'
)
if old_or in content:
    content = content.replace(old_or, new_or)
    print("  ✅ Onboarding ready (zh) updated")
else:
    print("  ❌ Onboarding ready not found")

# ─── FIX 14: allergen_journal zh header ───────────────────────────────────────
old_ajh = '"🥜 Allergen Journal" if language == "en" else "🥜 Registro de Alérgenos"'
new_ajh = '"🥜 Allergen Journal" if language == "en" else "🥜 过敏记录"'
if old_ajh in content:
    content = content.replace(old_ajh, new_ajh)
    print("  ✅ Allergen journal header (zh) updated")
else:
    print("  ❌ Allergen journal header not found")

# ─── FIX 15: allergen_journal no intro (zh) ───────────────────────────────────
old_ajni = '"No allergens introduced yet." if language == "en" else "Aún no se han introducido alérgenos."'
new_ajni = '"No allergens introduced yet." if language == "en" else "尚未引入任何过敏原。"'
if old_ajni in content:
    content = content.replace(old_ajni, new_ajni)
    print("  ✅ Allergen journal no-intro (zh) updated")
else:
    print("  ❌ Allergen journal no-intro not found")

# ─── FIX 16: allergen_journal hint (zh) ───────────────────────────────────────
old_ajhint = '"\\nLog with: /introduce <allergen>" if language == "en" else "\\nRegistra con: /introduce <alérgeno>"'
new_ajhint = '"\\nLog with: /introduce <allergen>" if language == "en" else "\\n记录方式：/introduce <过敏原>"'
if old_ajhint in content:
    content = content.replace(old_ajhint, new_ajhint)
    print("  ✅ Allergen journal hint (zh) updated")
else:
    print("  ❌ Allergen journal hint not found")

# ─── FIX 17: allergen_journal severity buttons (zh) ──────────────────────────
# These are in build_severity_keyboard - need to replace InlineKeyboardButton calls
old_sev = (
    'InlineKeyboardButton("✅ Tolerated", callback_data="intro_outcome_save:tolerated")\n'
    '        [InlineKeyboardButton("🚨 Reaction", callback_data="intro_outcome_save:reaction")\n'
    '        [InlineKeyboardButton("❓ Unknown", callback_data="intro_outcome_save:unknown")'
)
new_sev = (
    'InlineKeyboardButton("✅ 耐受良好", callback_data="intro_outcome_save:tolerated")\n'
    '        [InlineKeyboardButton("🚨 有反应", callback_data="intro_outcome_save:reaction")\n'
    '        [InlineKeyboardButton("❓ 未知", callback_data="intro_outcome_save:unknown")'
)
if old_sev in content:
    content = content.replace(old_sev, new_sev)
    print("  ✅ Severity keyboard (intro_outcome_save) updated")
else:
    print("  ❌ Severity keyboard (intro_outcome_save) not found")

# outcome:tolerated keyboard
old_sev2 = (
    'InlineKeyboardButton("✅ Tolerated", callback_data="outcome:tolerated")\n'
    '        [InlineKeyboardButton("🚨 Reaction", callback_data="outcome:reaction")\n'
    '        [InlineKeyboardButton("❓ Unknown", callback_data="outcome:unknown")'
)
new_sev2 = (
    'InlineKeyboardButton("✅ 耐受良好", callback_data="outcome:tolerated")\n'
    '        [InlineKeyboardButton("🚨 有反应", callback_data="outcome:reaction")\n'
    '        [InlineKeyboardButton("❓ 未知", callback_data="outcome:unknown")'
)
if old_sev2 in content:
    content = content.replace(old_sev2, new_sev2)
    print("  ✅ Severity keyboard (outcome) updated")
else:
    print("  ❌ Severity keyboard (outcome) not found")

# ─── FIX 18: allergen_journal severity prompt (zh) ────────────────────────────
old_sevp = 'f"Severidad: **{severity}**\\n\\n¿Cuál fue el resultado?"'
new_sevp = f'f"严重程度：**{{{{severity}}}}**\\n\\n结果如何？"'
if old_sevp in content:
    content = content.replace(old_sevp, new_sevp)
    print("  ✅ Severity prompt (zh) updated")
else:
    print("  ❌ Severity prompt not found")

# ─── FIX 19: allergen_journal "Registrando" (zh) ──────────────────────────────
old_reg = (
    'f"Logging: **{allergen.capitalize()}**\\n\\n"\n'
    '"How did it go? Tap a button below:"\n'
    '    )\n'
    '    if language == "zh":\n'
    '        prompt = f"Registrando: **{allergen.capitalize()}**\\n\\n"\n'
    '            "¿Cómo fue? Toca un botón abajo:"'
)
new_reg = (
    'f"Logging: **{allergen.capitalize()}**\\n\\n"\n'
    '"How did it go? Tap a button below:"\n'
    '    )\n'
    '    if language == "zh":\n'
    '        prompt = f"正在记录：**{{{{allergen.capitalize()}}}}**\\n\\n"\n'
    '            "结果如何？点击下方按钮："'
)
if old_reg in content:
    content = content.replace(old_reg, new_reg)
    print("  ✅ Registrando prompt (zh) updated")
else:
    print("  ❌ Registrando prompt not found")

# ─── FIX 20: allergen_journal quick-register (zh) ──────────────────────────────
old_qr = f"✅ {{allergen_cap}} registrado rápidamente."
new_qr = f"✅ {{allergen_cap}} 已快速记录。"
if old_qr in content:
    content = content.replace(old_qr, new_qr)
    print("  ✅ Quick-register (zh) updated")
else:
    print("  ❌ Quick-register not found")

# ─── FIX 21: allergen_journal "¿Cuál fue?" (zh) ───────────────────────────────
old_cual = '"¿Cuál fue el resultado?"'
new_cual = '"结果如何？"'
if old_cual in content:
    content = content.replace(old_cual, new_cual)
    print("  ✅ Cuál fue (zh) updated")
else:
    print("  ❌ Cuál fue not found")

# ─── FIX 22: allergen_journal introduce allergen usage ────────────────────────
old_usage_a = '"Which allergen are you introducing? (e.g., egg, peanut, milk)"'
new_usage_a = '"您正在引入哪种过敏原？（例如：鸡蛋、花生、牛奶）"'
if old_usage_a in content:
    content = content.replace(old_usage_a, new_usage_a)
    print("  ✅ Introduce allergen usage (zh) updated")
else:
    print("  ❌ Introduce allergen usage not found")

# ─── FIX 23: allergen_journal invalid allergen (zh) ───────────────────────────
old_inv1 = '"\'\\{allergen}\' no está en la lista. Alérgenos rastreables: {", ".join(ALLERGEN_TRACK_LIST)}"'
new_inv1 = '"\'\\{allergen}\'不在跟踪列表中。可跟踪的过敏原：{", ".join(ALLERGEN_TRACK_LIST)}"'
if old_inv1 in content:
    content = content.replace(old_inv1, new_inv1)
    print("  ✅ Invalid allergen 1 (zh) updated")
else:
    print("  ❌ Invalid allergen 1 not found")

old_inv2 = '"\'\\{allergen}\' no está en la lista. Rastreables: {" + ", ".join(ALLERGEN_TRACK_LIST) + "}"'
new_inv2 = '"\'\\{allergen}\'不在跟踪列表中。可跟踪的：{" + ", ".join(ALLERGEN_TRACK_LIST) + "}"'
if old_inv2 in content:
    content = content.replace(old_inv2, new_inv2)
    print("  ✅ Invalid allergen 2 (zh) updated")
else:
    print("  ❌ Invalid allergen 2 not found")

# ─── FIX 24: allergen_journal first-intro ─────────────────────────────────────
old_fi = f"✅ Registrada primera introducción de {{allergen_cap}} el {{now_str}}."
new_fi = f"✅ 已记录首次引入 {{allergen_cap}}，日期：{{now_str}}。"
if old_fi in content:
    content = content.replace(old_fi, new_fi)
    print("  ✅ First-intro (zh) updated")
else:
    print("  ❌ First-intro not found")

# ─── FIX 25: allergen_journal tip ─────────────────────────────────────────────
old_tip_aj = '"\\n\\n💡 Consejo: Sirve una pequeña cantidad y espera 3-4 días antes de introducir otro alérgeno nuevo."'
new_tip_aj = '"\\n\\n💡 建议：引入少量，等待3-4天再引入新的过敏原。"'
if old_tip_aj in content:
    content = content.replace(old_tip_aj, new_tip_aj)
    print("  ✅ Allergen tip (zh) updated")
else:
    print("  ❌ Allergen tip not found")

# ─── FIX 26: allergen_journal /introduce usage ─────────────────────────────────
old_ia = '"Usa /introduce <alérgeno> [reacciones], por ejemplo: /introduce maní o /introduce huevo sarpullido leve"'
new_ia = '"使用 /introduce <过敏原> [反应]，例如：/introduce 花生 或 /introduce 鸡蛋 轻度皮疹"'
if old_ia in content:
    content = content.replace(old_ia, new_ia)
    print("  ✅ /introduce usage (zh) updated")
else:
    print("  ❌ /introduce usage not found")

# ─── FIX 27: allergen_journal "¿Qué alérgeno?" (zh) ──────────────────────────
old_qa = '"¿Qué alérgeno estás introduciendo? (ej., huevo, maní, leche)"'
new_qa = '"您正在引入哪种过敏原？（例如：鸡蛋、花生、牛奶）"'
if old_qa in content:
    content = content.replace(old_qa, new_qa)
    print("  ✅ Qué alergeno (zh) updated")
else:
    print("  ❌ Qué alergeno not found")

# ─── FIX 28: allergen_journal quick option ────────────────────────────────────
old_qo = f"🥜 {{prompt}}\\n\\nOr use /introduce <alérgeno>"
new_qo = f"🥜 {{prompt}}\\n\\nOr use /introduce <过敏原>"
if old_qo in content:
    content = content.replace(old_qo, new_qo)
    print("  ✅ Quick option (zh) updated")
else:
    print("  ❌ Quick option not found")

# ─── FIX 29: allergen_journal footer ──────────────────────────────────────────
old_ftr = '"Usa los botones del menú o escribe un comando para continuar."'
new_ftr = '"使用菜单按钮或输入命令继续。"'
if old_ftr in content:
    content = content.replace(old_ftr, new_ftr)
    print("  ✅ Footer (zh) updated")
else:
    print("  ❌ Footer not found")

# ─── FIX 30: allergen_journal stats header (zh) ────────────────────────────────
old_stats = '"📊 Your Stats" if language == "en" else "📊 Tus Estadísticas"'
new_stats = '"📊 Your Stats" if language == "en" else "📊 您的统计"'
if old_stats in content:
    content = content.replace(old_stats, new_stats)
    print("  ✅ Stats header (zh) updated")
else:
    print("  ❌ Stats header not found")

# ─── FIX 31: allergen_journal follow-up ──────────────────────────────────────
old_fu = '"¡Sigue usando el bot para mejorar tus planes de comidas! 💪"'
new_fu = '"继续使用机器人来优化您的餐饮计划！💪"'
if old_fu in content:
    content = content.replace(old_fu, new_fu)
    print("  ✅ Follow-up (zh) updated")
else:
    print("  ❌ Follow-up not found")

# ─── FIX 32: allergen_journal cancel ─────────────────────────────────────────
old_cn = '"Cancelado. ¿Qué te gustaría hacer?"'
new_cn = '"已取消。请问您想做什么？"'
if old_cn in content:
    content = content.replace(old_cn, new_cn)
    print("  ✅ Cancel (zh) updated")
else:
    print("  ❌ Cancel not found")

# ─── FIX 33: allergen_journal feedback ────────────────────────────────────────
old_fb = '"¡Guardado tu feedback. Gracias!"'
new_fb = '"已保存您的反馈。谢谢！"'
if old_fb in content:
    content = content.replace(old_fb, new_fb)
    print("  ✅ Feedback (zh) updated")
else:
    print("  ❌ Feedback not found")

# ─── FIX 34: allergen_journal rating buttons ──────────────────────────────────
old_rating = '"👍 ¡Guardado!" if direction == "up" else ("👎 Recibido" if direction == "down" else "⭐ Omitido")'
new_rating = '"👍 已保存！" if direction == "up" else ("👎 已记录" if direction == "down" else "⭐ 已跳过")'
if old_rating in content:
    content = content.replace(old_rating, new_rating)
    print("  ✅ Rating (zh) updated")
else:
    print("  ❌ Rating not found")

# ─── FIX 35: allergen_journal "/start first" errors ─────────────────────────
for old_err in [
    '"Por favor usa /start primero para guardar tu perfil."',
    '"Por favor usa /start primero para guardar el perfil de tu bebé."',
]:
    new_err = '"请先运行 /start 来保存您的资料。"'
    if old_err in content:
        content = content.replace(old_err, new_err)
        print(f"  ✅ /start first error updated: {old_err[:50]}")

# ─── FIX 36: allergen_journal no_plan error ────────────────────────────────
for old_np in [
    '"Primero necesito un plan semanal. Toca Plan semanal y yo crearé uno para ti."',
    '"Primero necesito un plan semanal. Toca Plan semanal y yo crearé uno para ti."',
]:
    new_np = '"请先创建每周计划。点击"每周计划"我来为您生成。"'
    if old_np in content:
        content = content.replace(old_np, new_np)
        print(f"  ✅ No-plan error updated")

# ─── FIX 37: allergen_journal no inspiration ─────────────────────────────────
old_ni = '"No tengo una inspiración reciente para colocar. Envía una foto, enlace o idea de comida primero."'
new_ni = '"暂无最近的灵感可添加。请先发送照片、链接或餐饮想法。"'
if old_ni in content:
    content = content.replace(old_ni, new_ni)
    print("  ✅ No-inspiration (zh) updated")
else:
    print("  ❌ No-inspiration not found")

# ─── FIX 38: allergen_journal /apply error ───────────────────────────────────
old_ap_err = '"No pude actualizar esa comida de manera segura ahora. Por favor intenta de nuevo con una inspiración diferente."'
new_ap_err = '"无法安全更新该餐食。请尝试其他灵感。"'
if old_ap_err in content:
    content = content.replace(old_ap_err, new_ap_err)
    print("  ✅ /apply error (zh) updated")
else:
    print("  ❌ /apply error not found")

# ─── FIX 39: allergen_journal /rate usage ─────────────────────────────────────
old_rate = '"No pude leer tu calificación. Usa /rate <id> <up|down|0> [comentario]."'
new_rate = '"无法读取评分。使用 /rate <编号> <up|down|0> [评论]。"'
if old_rate in content:
    content = content.replace(old_rate, new_rate)
    print("  ✅ /rate usage (zh) updated")
else:
    print("  ❌ /rate usage not found")

# ─── FIX 40: allergen_journal /regenerate usage ─────────────────────────────
old_regen = '"Usa /regenerate <día> <comida>, por ejemplo: /regenerate wed lunch"'
new_regen = '"使用 /regenerate <日期> <餐次>，例如：/regenerate wed lunch"'
if old_regen in content:
    content = content.replace(old_regen, new_regen)
    print("  ✅ /regenerate usage (zh) updated")
else:
    print("  ❌ /regenerate usage not found")

# ─── FIX 41: allergen_journal quick-apply usage ─────────────────────────────
old_qa_usage = (
    '"Usa /apply <inspiration_id> <día> <comida>, por ejemplo: /apply 12 mon dinner.\\n"'
    '"Una opción más simple es responder con \\"Use 1 for Wednesday dinner\\" después de que sugiera ideas de comida."'
)
new_qa_usage = (
    '"使用 /apply <灵感编号> <星期> <餐次>，例如：/apply 12 mon dinner。\\n"'
    '"更简单的方式是在我建议后回复如"选择1作为周三晚餐"。'
)
if old_qa_usage in content:
    content = content.replace(old_qa_usage, new_qa_usage)
    print("  ✅ Quick-apply usage (zh) updated")
else:
    print("  ❌ Quick-apply usage not found")

# ─── FIX 42: allergen_journal set_age usage ─────────────────────────────────
old_sa = '"Usa /set_age <meses>, por ejemplo: /set_age 12"'
new_sa = '"使用 /set_age <月龄>，例如：/set_age 12"'
if old_sa in content:
    content = content.replace(old_sa, new_sa)
    print("  ✅ set_age usage (zh) updated")
else:
    print("  ❌ set_age usage not found")

# ─── FIX 43: allergen_journal age prompt (allergy_step) ─────────────────────
old_age_p = '"Por favor envía la edad de tu bebé en meses, por ejemplo: 12"'
new_age_p = '"请发送您宝宝的月龄，例如：12"'
if old_age_p in content:
    content = content.replace(old_age_p, new_age_p)
    print("  ✅ Age prompt (zh) updated")
else:
    print("  ❌ Age prompt not found")

# ─── FIX 44: allergen_journal allergies prompt ───────────────────────────────
old_all_p = '"Por favor envía las alergias como una lista separada por comas, o responde con none."'
new_all_p = '"请以逗号分隔发送过敏原列表，或回复none表示无过敏。"'
if old_all_p in content:
    content = content.replace(old_all_p, new_all_p)
    print("  ✅ Allergies prompt (zh) updated")
else:
    print("  ❌ Allergies prompt not found")

# ─── FIX 45: allergen_journal quick-apply day/food error ────────────────────
old_df_err = '"Por favor usa un día (Mon-Sun) y comida (breakfast, lunch, dinner, snack1, snack2)."'
new_df_err = '"请使用日期（Mon-Sun）和餐次（breakfast、lunch、snack1、snack2、dinner）。"'
if old_df_err in content:
    content = content.replace(old_df_err, new_df_err)
    print("  ✅ Day/food error (zh) updated")
else:
    print("  ❌ Day/food error not found")

# ─── FIX 46: allergen_journal /apply inspiration number error ──────────────
old_ap_num = '"No pude leer ese número de inspiración."'
new_ap_num = '"无法读取灵感编号。"'
if old_ap_num in content:
    content = content.replace(old_ap_num, new_ap_num)
    print("  ✅ Inspiration number error (zh) updated")
else:
    print("  ❌ Inspiration number error not found")

# ─── FIX 47: allergen_journal /apply day/food error ─────────────────────────
old_ap_df = '"No pude entender el día o la comida. Usa: Mon, Tue, Wed, Thu, Fri, Sat, Sun y breakfast, lunch, snack1, snack2, dinner."'
new_ap_df = '"无法识别日期或餐次。使用：Mon、Tue、Wed、Thu、Fri、Sat、Sun 和 breakfast、lunch、snack1、snack2、dinner。"'
if old_ap_df in content:
    content = content.replace(old_ap_df, new_ap_df)
    print("  ✅ /apply day/food error (zh) updated")
else:
    print("  ❌ /apply day/food error not found")

# ─── FIX 48: allergen_journal /apply inspiration not found ────────────────
old_ap_nf = '"No pude encontrar esa inspiración guardada."'
new_ap_nf = '"找不到该保存的灵感。"'
if old_ap_nf in content:
    content = content.replace(old_ap_nf, new_ap_nf)
    print("  ✅ Inspiration not found (zh) updated")
else:
    print("  ❌ Inspiration not found not found")

# ─── FIX 49: allergen_journal quick-apply simpler option ───────────────────
old_sim = '"A simpler option is to reply with \\"Use 1 for Wednesday dinner\\" after I suggest meal ideas."'
new_sim = '"更简单的方式是在我建议后回复如"选择1作为周三晚餐"。"'
if old_sim in content:
    content = content.replace(old_sim, new_sim)
    print("  ✅ Simpler option (zh) updated")
else:
    print("  ❌ Simpler option not found")

# ─── FIX 50: allergen_journal /apply usage ─────────────────────────────────
old_ap_u = '"No pude entender el día o la comida. Usa: Mon, Tue, Wed, Thu, Fri, Sat, Sun y breakfast, lunch, snack1, snack2, dinner."'
if old_ap_u in content:
    content = content.replace(old_ap_u, new_ap_df)
    print("  ✅ /apply usage (zh) updated")

# ─── FIX 51: quick_apply image error ────────────────────────────────────────
old_img = '"Lo siento, no pude procesar esa imagen. Prueba con otra foto o envía una idea de comida."'
new_img = '"无法处理该图片。请尝试发送其他照片或餐饮想法。"'
if old_img in content:
    content = content.replace(old_img, new_img)
    print("  ✅ Image error (zh) updated")
else:
    print("  ❌ Image error not found")

# ─── FIX 52: allergen_journal - allergen safety note ────────────────────────
old_safety1 = '"[Sustitución automática tras revisión de seguridad — consulte al pediatra]"'
new_safety1 = '"[经安全审查后自动替换 — 请咨询儿科医生]"'
if old_safety1 in content:
    content = content.replace(old_safety1, new_safety1)
    print("  ✅ Safety note 1 (zh) updated")
else:
    print("  ❌ Safety note 1 not found")

old_safety2 = '"[Opción segura generada automáticamente — consulte al pediatra]"'
new_safety2 = '"[自动生成的安全替代品 — 请咨询儿科医生]"'
if old_safety2 in content:
    content = content.replace(old_safety2, new_safety2)
    print("  ✅ Safety note 2 (zh) updated")
else:
    print("  ❌ Safety note 2 not found")

# ─── FIX 53: allergen_journal tip (allergen journal) ─────────────────────────
old_tip2 = '"💡 Consejo: Sirve alimentos ricos en hierro con vitamina C (ej., fresa con cereal fortificado) para mejorar la absorción."'
new_tip2 = '"💡 建议：将富含铁的食物与维生素C一起食用（例如草莓配强化谷物）以促进吸收。"'
if old_tip2 in content:
    content = content.replace(old_tip2, new_tip2)
    print("  ✅ Iron tip (zh) updated")
else:
    print("  ❌ Iron tip not found")

# Write the file
with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print(f"\nFile written: {path}")
