#!/usr/bin/env python3
"""
Comprehensive Spanish→Chinese fix for baby_feeding_bot.py.
Run: python scripts/fix_spanish_to_chinese.py
"""
import re

path = "/home/deploy/baby-feeding-bot/baby_feeding_bot.py"
with open(path, encoding="utf-8") as f:
    content = f.read()

def replace(old, new):
    if old in content:
        content = content.replace(old, new)
        print(f"  ✅ {old[:60]}")
        return True
    else:
        print(f"  ❌ NOT FOUND: {old[:60]}")
        return False

def fix_file():
    changes = 0

    # ── Shopping list improvements ──────────────────────────────────────────────
    # The _render_shopping_list_from_json: replace entirely with user-friendly version
    old_sl = '''def _render_shopping_list_from_json(raw: str, language: str = "en") -> str:
    """
    Parse LLM JSON response and render as formatted shopping list.
    Falls back to stripped text if JSON parsing fails.
    """
    header = "🛒 Shopping List" if language == "en" else "🛒 购物清单"
    try:
        # Strip markdown code fences
        cleaned = re.sub(r"```(?:json)?\\s*", "", raw.strip()).strip()
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("Not a dict")
    except Exception:
        # Fallback: strip any remaining markdown and return as-is
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
    Falls back to a smart text formatter if JSON parsing fails.
    """
    header = "🛒 Shopping List" if language == "en" else "🛒 购物清单"
    fallback_header_map = {
        "en": "🛒 Shopping List\\n\\nCould not parse — here are the items:",
        "zh": "🛒 购物清单\\n\\n无法解析 — 以下是提取的物品：",
    }
    fallback_header = fallback_header_map.get(language, fallback_header_map["en"])

    # ── Attempt JSON parse ─────────────────────────────────────────────────────
    try:
        cleaned = re.sub(r"```(?:json)?\\s*", "", raw.strip()).strip()
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("Not a dict")
    except Exception:
        # Smart fallback: parse unstructured text and format nicely
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

    # ── JSON parsed: render with emoji checkmarks + quantities ─────────────────
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

    # Footer with item count
    count_map = {
        "en": f"Total: {total_items} items",
        "zh": f"共 {total_items} 项",
    }
    count_label = count_map.get(language, count_map["en"])
    lines_out.extend(["", f"✅ {count_label}"])
    return "\\n".join(lines_out)'''

    if old_sl in content:
        content = content.replace(old_sl, new_sl)
        print(f"  ✅ Replaced shopping list renderer")
    else:
        print(f"  ❌ Shopping list renderer NOT FOUND (may already be updated)")

    # ── Shopping list generation prompt: fix Rules: literal \n → real newlines ──
    old_prompt = ('"Given the ingredients below (already deduplicated), create a clean shopping list.\\n"'
                  '"Group items into exactly these 5 categories:\\n"'
                  '"🥦 Produce  🥩 Protein  🧀 Dairy  🫙 Pantry  📦 Other\\n\\n"'
                  '"Rules:\\n"'
                  '"- Use the quantities provided (e.g., 3× carrots). If no quantity is given, list the item once.\\n"'
                  '"- Skip salt, sugar, and seasoning items.\\n"'
                  '"- Keep each category concise (max 8 items per category).\\n"'
                  '"- Respond ONLY with valid JSON in this exact structure (no markdown, no explanation):\\n"'
                  '\'{"produce": ["item1", "item2"], "protein": [], "dairy": [], "pantry": [], "other": []}\\n\\n\'')
    new_prompt = ('"Given the ingredients below (already deduplicated), create a clean shopping list.\\n"'
                  '"Group items into exactly these 5 categories:\\n"'
                  '"🥦 Produce  🥩 Protein  🧀 Dairy  🫙 Pantry  📦 Other\\n\\n"'
                  '"Rules:\\n"'
                  '"- Include quantities where given (e.g., 150g carrots, ½ avocado). '
                  'For items without quantity, add a typical household amount for a baby portion.\\n"'
                  '"- Skip salt, sugar, and seasonings.\\n"'
                  '"- Keep each category concise (max 8 items).\\n"'
                  '"- Respond ONLY with valid JSON in this exact structure (no markdown, no explanation):\\n"'
                  '\'{"produce": ["150g carrots", "½ avocado"], "protein": ["100g chicken"], "dairy": [], "pantry": [], "other": []}\\n\\n\'')
    if old_prompt in content:
        content = content.replace(old_prompt, new_prompt)
        print(f"  ✅ Fixed shopping list generation prompt (quantity guidance)")
    else:
        print(f"  ❌ Shopping list prompt NOT FOUND")

    # ── main_menu_markup: dynamic language button ───────────────────────────────
    old_mm = '''def main_menu_markup() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(MAIN_MENU_ROWS, resize_keyboard=True)'''
    new_mm = '''def main_menu_markup(language: Optional[str] = None, telegram_user_id: Optional[int] = None) -> ReplyKeyboardMarkup:
    if language is None and telegram_user_id is not None:
        language = get_user_language(telegram_user_id, "en")
    if language is None:
        language = "en"
    lang_label = {"en": "🌐 中文", "zh": "🌐 English"}.get(language, "🌐 Lang")
    rows: List[List[str]] = [
        ["📆 Today", "📅 Weekly plan"],
        ["🛒 Shopping list", "📚 History"],
        ["👶 Update age", "🥜 Update allergies"],
        ["🥜 Allergen journal", "❓ Help"],
        [lang_label, "👤 Profile"],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)'''
    if old_mm in content:
        content = content.replace(old_mm, new_mm)
        print(f"  ✅ Fixed main_menu_markup (dynamic language button)")
    else:
        print(f"  ❌ main_menu_markup NOT FOUND")

    # ── MENU_TO_ACTION: update language button key ──────────────────────────────
    old_ta = '"🌐 EN/ES": "toggle_lang"'
    new_ta = '"🌐 Lang": "toggle_lang"'
    if old_ta in content:
        content = content.replace(old_ta, new_ta)
        print(f"  ✅ Fixed MENU_TO_ACTION language key")
    else:
        print(f"  ❌ MENU_TO_ACTION key NOT FOUND")

    # ── Fix all Spanish strings (single-line replacements) ───────────────────
    singles = [
        # /start onboarding welcome-back (returning user zh branch)
        ('"¡Bienvenido de vuelta 👋\\n\\n"\n'
         '"¿Qué te gustaría hacer hoy?\\n"\n'
         '"• Crear o ver tu plan semanal\\n"\n'
         '"• Obtener una lista de compras\\n"\n'
         '"• Enviar una nueva foto o idea de comida\\n\\n"\n'
         '"También puedes responder con algo como \\"Use 1 for Wednesday dinner\\" después de que sugiera opciones de comida."',
         '"欢迎回来 👋\\n\\n"\n'
         '"今天想做什么？\\n"\n'
         '"• 创建或查看每周计划\\n"\n'
         '"• 获取购物清单\\n"\n'
         '"• 发送新的食物照片或餐饮想法\\n\\n"\n'
         '"在我建议餐食选项后，您也可以回复如"选择1作为周三晚餐"来添加餐食。"'),
        # /start onboarding intro (zh locale)
        ('"¡Hola! Soy tu asistente de alimentación infantil 🍼\\n\\n"\n'
         '"Te ayudo a:\\n"\n'
         '"• Convertir ideas de comida en comidas seguras para bebés\\n"\n'
         '"• Crear planes semanales de comidas\\n"\n'
         '"• Hacer listas de compras\\n\\n"\n'
         '"Para empezar, ¿cuántos meses tiene tu bebé?\\n"\n'
         '"(Responde con un número, o envía skip para usar 12 meses)"',
         '"你好！我是您的宝宝喂养助手 🍼\\n\\n"\n'
         '"我可以帮助您：\\n"\n'
         '"• 将餐饮想法转化为宝宝安全的餐食\\n"\n'
         '"• 创建每周饮食计划\\n"\n'
         '"• 生成购物清单\\n\\n"\n'
         '"首先，您的宝宝多大（按月计算）？\\n"\n'
         '"（回复数字，或发送skip使用12个月默认值）"'),
        # /start onboarding allergies step (zh locale)
        ('"¿Alguna alergia o alimento a evitar?\\n"\n'
         '"Responde con una lista separada por comas, o envía none."',
         '"您的宝宝有过敏或需要避免的食物吗？\\n"\n'
         '"请以逗号分隔回复，或发送none表示无过敏。"'),
        # /start onboarding ready (zh locale)
        ('"¡Todo listo ✨\\n\\n"\n'
         '"A continuación, envía una foto de comida, un enlace o una idea de comida y la convertiré en opciones seguras para bebés.\\n"\n'
         '"Cuando estés listo, toca Plan semanal para crear el horario de la próxima semana."',
         '"一切就绪 ✨\\n\\n"\n'
         '"现在，发送食物照片、链接或餐饮想法，我会将其转化为适合宝宝的安全选项。\\n"\n'
         '"准备就绪后，点击"每周计划"来创建下周的饮食安排。"'),
        # allergen journal severity prompt
        ('f"Severidad: **{severity}**\\n\\n¿Cuál fue el resultado?"',
         f'f"严重程度：**{{severity}}**\\n\\n结果如何？"}'),
        # allergen journal severity keyboard buttons (zh)
        ('InlineKeyboardButton("✅ Tolerated", callback_data="intro_outcome_save:tolerated")\n'
         '        InlineKeyboardButton("🚨 Reaction", callback_data="intro_outcome_save:reaction")\n'
         '        InlineKeyboardButton("❓ Unknown", callback_data="intro_outcome_save:unknown")',
         'InlineKeyboardButton("✅ 耐受良好", callback_data="intro_outcome_save:tolerated")\n'
         '        InlineKeyboardButton("🚨 有反应", callback_data="intro_outcome_save:reaction")\n'
         '        InlineKeyboardButton("❓ 未知", callback_data="intro_outcome_save:unknown")'),
        # allergen journal keyboard buttons
        ('InlineKeyboardButton("✅ Tolerated", callback_data="outcome:tolerated")\n'
         '        InlineKeyboardButton("🚨 Reaction", callback_data="outcome:reaction")\n'
         '        InlineKeyboardButton("❓ Unknown", callback_data="outcome:unknown")',
         'InlineKeyboardButton("✅ 耐受良好", callback_data="outcome:tolerated")\n'
         '        InlineKeyboardButton("🚨 有反应", callback_data="outcome:reaction")\n'
         '        InlineKeyboardButton("❓ 未知", callback_data="outcome:unknown")'),
        # allergen journal severity (logging prompt zh)
        ('f"Registrando: **{allergen.capitalize()}**\\n\\n"\n'
         '"¿Cómo fue? Toca un botón abajo:"',
         f'f"正在记录：**{{allergen.capitalize()}}**\\n\\n"\n'
         '"结果如何？点击下方按钮："'),
        # allergen journal severity (message reply zh)
        ('"¿Cuál fue el resultado?"',
         '"结果如何？"'),
        # allergen journal quick register zh
        ('f"✅ {allergen_cap} registrado rápidamente."',
         f'f"✅ {{allergen_cap}} 已快速记录。"'),
        # allergen journal hint
        ('"\\nLog with: /introduce <allergen>" if language == "en" else "\\nRegistra con: /introduce <alérgeno>"',
         '"\\nLog with: /introduce <allergen>" if language == "en" else "\\n记录方式：/introduce <过敏原>"'),
        # allergen journal no intro
        ('"No allergens introduced yet." if language == "en" else "Aún no se han introducido alérgenos."',
         '"No allergens introduced yet." if language == "en" else "尚未引入任何过敏原。"'),
        # allergen journal header
        ('"🥜 Allergen Journal" if language == "en" else "🥜 Registro de Alérgenos"',
         '"🥜 Allergen Journal" if language == "en" else "🥜 过敏记录"'),
        # allergen introduce /start first error
        ('error_msg = "Por favor usa /start primero para guardar tu perfil."',
         'error_msg = "请先运行 /start 来保存您的资料。"'),
        # allergen introduce usage
        ('"Which allergen are you introducing? (e.g., egg, peanut, milk)"',
         '"您正在引入哪种过敏原？（例如：鸡蛋、花生、牛奶）"'),
        # allergen introduce invalid
        ('"\'\\{allergen}\' no está en la lista. Alérgenos rastreables: {', '.join(ALLERGEN_TRACK_LIST)}"',
         '"\'\\{allergen}\'不在跟踪列表中。可跟踪的过敏原：{", ".join(ALLERGEN_TRACK_LIST)}"'),
        # allergen journal allergen intro (invalid)
        ('"\'\\{allergen}\' no está en la lista. Rastreables: {',
         '"\'\\{allergen}\'不在跟踪列表中。可跟踪的：{'),
        # allergen journal hint (second occurrence)
        ('"\nRegistra con: /introduce <alérgeno>"',
         '"\\n记录方式：/introduce <过敏原>"'),
        # allergen journal severity tip
        ('"\\n\\n💡 Consejo: Sirve una pequeña cantidad y espera 3-4 días antes de introducir otro alérgeno nuevo."',
         '"\\n\\n💡 建议：引入少量，等待3-4天再引入新的过敏原。"'),
        # allergen journal first-intro confirmation
        ('f"✅ Registrada primera introducción de {allergen_cap} el {now_str}."',
         f'f"✅ 已记录首次引入 {{allergen_cap}}，日期：{{now_str}}。"'),
        # /start error messages
        ('"Por favor usa /start primero para guardar el perfil de tu bebé."',
         '"请先运行 /start 来保存宝宝资料。"'),
        # set_age usage (zh)
        ('"Usa /set_age <meses>, por ejemplo: /set_age 12"',
         '"使用 /set_age <月龄>，例如：/set_age 12"'),
        # quick_apply error
        ('"Primero necesito un plan semanal. Toca Plan semanal y yo crearé uno para ti."',
         '"请先创建每周计划。点击"每周计划"我来为您生成。"'),
        # history no plans
        ('"No weekly plans yet." if language == "en" else "Aún no hay planes semanales."',
         '"No weekly plans yet." if language == "en" else "暂无每周计划。"'),
        # history no inspirations
        ('"No saved inspirations yet." if language == "en" else "Aún no hay inspiraciones guardadas."',
         '"No saved inspirations yet." if language == "en" else "暂无保存的灵感。"'),
        # history empty plans error
        ('"Primero necesito un plan semanal. Toca Plan semanal y yo crearé uno para ti."',
         '"请先创建每周计划。点击"每周计划"我来为您生成。"'),
        # quick_apply handler - "Lo siento"
        ('"Lo siento, no pude procesar esa imagen. Prueba con otra foto o envía una idea de comida."',
         '"无法处理该图片。请尝试发送其他照片或餐饮想法。"'),
        # quick_apply inspiration not found
        ('"No tengo una inspiración reciente para colocar. Envía una foto, enlace o idea de comida primero."',
         '"暂无最近的灵感可添加。请先发送照片、链接或餐饮想法。"'),
        # /apply usage (zh)
        ('"A simpler option is to reply with \\"Use 1 for Wednesday dinner\\" after I suggest meal ideas."',
         '"更简单的方式是在我建议后回复如"选择1作为周三晚餐"。"'),
        # /apply inspiration not found (zh)
        ('"No pude leer ese número de inspiración."',
         '"无法读取灵感编号。"'),
        # /apply not found (zh)
        ('"No pude encontrar esa inspiración guardada."',
         '"找不到该保存的灵感。"'),
        # /apply day/food error (zh)
        ('"No pude entender el día o la comida. Usa: Mon, Tue, Wed, Thu, Fri, Sat, Sun y breakfast, lunch, snack1, snack2, dinner."',
         '"无法识别日期或餐次。使用：Mon、Tue、Wed、Thu、Fri、Sat、Sun 和 breakfast、lunch、snack1、snack2、dinner。"'),
        # /rate usage (zh)
        ('"No pude leer tu calificación. Usa /rate <id> <up|down|0> [comentario]."',
         '"无法读取评分。使用 /rate <编号> <up|down|0> [评论]。"'),
        # quick_apply day/food error (zh)
        ('"Por favor usa un día (Mon-Sun) y comida (breakfast, lunch, dinner, snack1, snack2)."',
         '"请使用日期（Mon-Sun）和餐次（breakfast、lunch、snack1、snack2、dinner）。"'),
        # /regenerate usage (zh)
        ('"Usa /regenerate <día> <comida>, por ejemplo: /regenerate wed lunch"',
         '"使用 /regenerate <日期> <餐次>，例如：/regenerate wed lunch"'),
        # allergen allergen journal /apply error
        ('"Primero necesito un plan semanal. Toca Plan semanal y yo crearé uno para ti."',
         '"请先创建每周计划。点击"每周计划"我来为您生成。"'),
        # allergen journal /apply error
        ('"Por favor usa /start primero para guardar el perfil de tu bebé."',
         '"请先运行 /start 来保存宝宝资料。"'),
        # allergen journal introduce allergen usage (zh)
        ('"Usa /introduce <alérgeno> [reacciones], por ejemplo: /introduce maní o /introduce huevo sarpullido leve"',
         '"使用 /introduce <过敏原> [反应]，例如：/introduce 花生 或 /introduce 鸡蛋 轻度皮疹"'),
        # allergen journal quick option (zh)
        ('f"🥜 {prompt}\\n\\nOr use /introduce <alérgeno>"',
         f'f"🥜 {{prompt}}\\n\\nOr use /introduce <过敏原>"'),
        # allergen journal footer
        ('"\\nUsa los botones del menú o escribe un comando para continuar."',
         '"\\n使用菜单按钮或输入命令继续。"'),
        # allergen journal stats
        ('"📊 Your Stats" if language == "en" else "📊 Tus Estadísticas"',
         '"📊 Your Stats" if language == "en" else "📊 您的统计"'),
        # allergen journal no plan error
        ('"No tengo una inspiración reciente para colocar. Envía una foto, enlace o idea de comida primero."',
         '"暂无最近的灵感可添加。请先发送照片、链接或餐饮想法。"'),
        # allergen journal no plan
        ('"Primero necesito un plan semanal. Toca Plan semanal y yo crearé uno para ti."',
         '"请先创建每周计划。点击"每周计划"我来为您生成。"'),
        # allergen journal - meal update error
        ('"No pude actualizar esa comida de manera segura ahora. Por favor intenta de nuevo con una inspiración diferente."',
         '"无法安全更新该餐食。请尝试其他灵感。"'),
        # allergen journal quick-add footer (zh)
        ('"Usa los botones del menú o escribe un comando para continuar."',
         '"使用菜单按钮或输入命令继续。"'),
        # allergen journal - allergen result (severity)
        ('f"Severidad: **{severity}**\\n\\n¿Cuál fue el resultado?"',
         f'f"严重程度：**{{severity}}**\\n\\n结果如何？"}'),
        # allergen journal quick-register
        ('f"✅ {allergen_cap} registrado rápidamente."',
         f'f"✅ {{allergen_cap}} 已快速记录。"'),
        # allergen journal - allergen intro help text
        ('"Which allergen are you introducing? (e.g., egg, peanut, milk)"',
         '"您正在引入哪种过敏原？（例如：鸡蛋、花生、牛奶）"'),
        # allergen journal - severity buttons (inline keyboard)
        ('InlineKeyboardButton("✅ Tolerated", callback_data="outcome:tolerated")\n'
         '        InlineKeyboardButton("🚨 Reaction", callback_data="outcome:reaction")\n'
         '        InlineKeyboardButton("❓ Unknown", callback_data="outcome:unknown")',
         'InlineKeyboardButton("✅ 耐受良好", callback_data="outcome:tolerated")\n'
         '        InlineKeyboardButton("🚨 有反应", callback_data="outcome:reaction")\n'
         '        InlineKeyboardButton("❓ 未知", callback_data="outcome:unknown")'),
    ]

    for old, new in singles:
        if old in content:
            content = content.replace(old, new)
            print(f"  ✅ {old[:60]}")
        else:
            print(f"  ❌ NOT FOUND: {old[:60]}")

    # ── Two-part fixes (multi-line) ─────────────────────────────────────────────
    # allergen severity prompt (in allergen_journal_handler zh branch)
    part1 = ('prompt = f"Severity: **{severity}**\\n\\nWhat was the outcome?"\n'
             '    if language == "zh":\n'
             '        prompt = f"Severidad: **{severity}**\\n\\n¿Cuál fue el resultado?"')
    part1_fix = ('prompt = f"Severity: **{severity}**\\n\\nWhat was the outcome?"\n'
                 '    if language == "zh":\n'
                 '        prompt = f"严重程度：**{{severity}}**\\n\\n结果如何？"')
    if part1 in content:
        content = content.replace(part1, part1_fix)
        print(f"  ✅ Fixed allergen severity prompt (zh)")
    else:
        print(f"  ❌ allergen severity prompt NOT FOUND")

    # allergen severity keyboard (allergen_journal_handler zh)
    part2 = ('InlineKeyboardButton("✅ Tolerated", callback_data="intro_outcome_save:tolerated")\n'
             '        InlineKeyboardButton("🚨 Reaction", callback_data="intro_outcome_save:reaction")\n'
             '        InlineKeyboardButton("❓ Unknown", callback_data="intro_outcome_save:unknown")')
    part2_fix = ('InlineKeyboardButton("✅ 耐受良好", callback_data="intro_outcome_save:tolerated")\n'
                 '        InlineKeyboardButton("🚨 有反应", callback_data="intro_outcome_save:reaction")\n'
                 '        InlineKeyboardButton("❓ 未知", callback_data="intro_outcome_save:unknown")')
    if part2 in content:
        content = content.replace(part2, part2_fix)
        print(f"  ✅ Fixed allergen severity keyboard (intro_outcome_save)")
    else:
        print(f"  ❌ allergen severity keyboard NOT FOUND")

    # allergen severity logging prompt (zh)
    part3 = ('f"Logging: **{allergen.capitalize()}**\\n\\n"\n'
             '        "How did it go? Tap a button below:"\n'
             '    )\n'
             '    if language == "zh":\n'
             '        prompt = f"Registrando: **{allergen.capitalize()}**\\n\\n"\n'
             '            "结果如何？点击下方按钮："')
    part3_fix = ('f"Logging: **{allergen.capitalize()}**\\n\\n"\n'
                 '        "How did it go? Tap a button below:"\n'
                 '    )\n'
                 '    if language == "zh":\n'
                 '        prompt = f"正在记录：**{{allergen.capitalize()}}**\\n\\n"\n'
                 '            "结果如何？点击下方按钮："')
    if part3 in content:
        content = content.replace(part3, part3_fix)
        print(f"  ✅ Fixed severity logging prompt (zh)")
    else:
        print(f"  ❌ severity logging prompt NOT FOUND")

    # allergen journal severity (line ~3507 in the update reply)
    part4 = ('f"Logging: **{allergen.capitalize()}**\\n\\n"\n'
             '"How did it go? Tap a button below:"')
    part4_fix = ('f"Logging: **{allergen.capitalize()}**\\n\\n"\n'
                  '"How did it go? Tap a button below:"')
    if part4 in content:
        # Only fix the zh branch, not the en branch
        pass  # Already handled in the zh-specific replacement

    # fix "Registrando" in update.message.reply_text
    part5 = ('f"Registrando: **{allergen.capitalize()}**\\n\\n"\n'
             '"结果如何？点击下方按钮："')
    part5_fix = ('f"正在记录：**{{allergen.capitalize()}}**\\n\\n"\n'
                 '"结果如何？点击下方按钮："')
    if part5 in content:
        content = content.replace(part5, part5_fix)
        print(f"  ✅ Fixed Registrando in reply_text (zh)")
    else:
        print(f"  ❌ Registrando in reply_text NOT FOUND")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"\nFile written: {path}")

if __name__ == "__main__":
    fix_file()
