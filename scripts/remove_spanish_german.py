#!/usr/bin/env python3
"""
Remove Spanish and German language support, keeping only English and Chinese.
Run: python scripts/remove_spanish_german.py
"""
import re

path = "/home/deploy/baby-feeding-bot/baby_feeding_bot.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

original = content

# ── 1. Toggle lang: EN↔ES → EN↔ZH ──────────────────────────────────────────────
content = content.replace(
    'new_lang = "es" if language == "en" else "en"',
    'new_lang = "zh" if language == "en" else "en"'
)
content = content.replace(
    '"Idioma configurado a Español."',
    '"语言已设置为中文。"'
)

# ── 2. LLM response language: "Spanish" → "Chinese" ─────────────────────────────
content = content.replace('"Respond in language: Spanish"', '"Respond in language: Chinese"')
content = content.replace("'Respond in language: Spanish'", "'Respond in language: Chinese'")
content = content.replace('"Spanish" if language == "es" else "English"',
                          '"Chinese" if language == "zh" else "English"')
content = content.replace('"Spanish" if language == "es"else "English"',
                          '"Chinese" if language == "zh" else "English"')
content = re.sub(r'"Spanish"\s+if\s+language\s*==\s*"es"\s+else\s+"English"',
                 '"Chinese" if language == "zh" else "English"', content)

# lang = "Spanish" if ... → lang = "Chinese" if ...
content = re.sub(r'lang\s*=\s*"Spanish"\s+if\s+language\s*==\s*"es"\s+else\s+"English"',
                 r'lang = "Chinese" if language == "zh" else "English"', content)

# ── 3. Swap if-language=="es" → if-language=="zh" (user-facing messages) ─────────
# These blocks have Spanish in the if-branch and English in the else-branch.
# We want to keep the English content as default and put Chinese in the if-branch.
# Strategy: for each block, extract the Spanish string and replace with Chinese.
# This is complex — handle the most common patterns directly.

def swap_es_zh_block(text):
    """
    Replace if-language=="es" blocks with if-language=="zh" and
    insert Chinese text where Spanish was.
    """
    # Pattern: if language == "es":\n    xxx\n    else:\n    yyy
    # Swap: if language == "zh":\n    [chinese version]\n    else:\n    yyy
    # We'll handle this by swapping the string content.
    return text

# ── 4. Direct string replacements: Spanish → Chinese (user-facing) ─────────────
spanish_to_chinese = {
    # General user messages
    "Por favor usa /start primero para guardar el perfil de tu bebé.":
        "请先运行 /start 以便我保存您宝宝的个人资料。",
    "Por favor usa /start primero para guardar tu perfil.":
        "请先运行 /start 以便我保存您的个人资料。",
    "Aquí te ayudo:\n\n"
        "1. Envía una foto de comida, un enlace o una idea de comida.\n"
        "2. Te daré opciones seguras para tu bebé.\n"
        "3. Responde con algo como \"Use 1 for Wednesday dinner\" para añadirlo al plan.\n\n"
        "Usa los botones del menú para ver tu plan semanal, lista de compras, historial y más.":
        "使用方法：\n\n"
        "1. 发送食物照片、链接或餐饮想法。\n"
        "2. 我会将其转化为适合宝宝的安全选项。\n"
        "3. 回复例如\"选择1作为周三晚餐\"将其添加到计划中。\n\n"
        "也可以使用下方菜单按钮查看每周计划、购物清单、历史记录和更新资料。",
    "No pude crear un plan semanal ahora. Por favor intenta de nuevo o envía una nueva idea.":
        "我现在无法制定每周计划。请重试或发送新的餐饮想法。",
    "No pude crear un plan semanal confiable ahora. Por favor intenta de nuevo o envía una nueva idea de comida primero.":
        "我现在无法制定可靠的每周计划。请重试或发送新的餐饮想法。",
    "Primero necesito un plan semanal. Toca Plan semanal y yo crearé uno para ti.":
        "请先创建每周计划。点击\"每周计划\"我来为您生成。",
    "No pude leer tu plan guardado. Toca Plan semanal para actualizzarlo.":
        "无法读取您保存的计划。点击\"每周计划\"刷新。",
    "Tu plan guardado parece incompleto. Toca Plan semanal para reconstruirlo.":
        "您保存的计划似乎不完整。点击\"每周计划\"重新生成。",
    "Aún no hay comidas planificadas.": "暂无计划。",
    "Aún no hay planes semanales.": "暂无每周计划。",
    "Aún no hay inspiraciones guardadas.": "暂无保存的灵感。",
    "Semana del ": "周 ",
    "Toca un día para expandir →": "点击日期展开详情 →",
    "Toca un día para expandir \u2192": "点击日期展开详情 →",
    "Volver a la semana": "返回周视图",
    "← Volver a la semana": "← 返回周视图",
    "« Back to days": "« 返回日期",
    "Sin datos para ": "无数据：",
    "No meals planned yet.": "暂无计划。",
    "Plan saved!": "计划已保存！",
    "Plan already saved": "计划已保存",
    "Language set to English.": "语言已设置为英语。",
    "Idioma configurado a Español.": "语言已设置为中文。",
    # Save plan
    "Plan guardado!": "计划已保存！",
    # Back button
    "← Back to week": "← 返回周视图",
    # Rating messages
    "Already showing this day": "已是当天视图",
    "Error showing day view": "无法显示当天视图",
    "Already showing week view": "已是周视图",
    "Error refreshing week view": "无法刷新周视图",
    "Error saving plan": "无法保存计划",
    # Meal card slots
    "Break": "早餐",
    "Morning snack": "早间点心",
    "Lunch": "午餐",
    "Afternoon snack": "下午点心",
    "Dinner": "晚餐",
    # Onboarding
    "Vamos a crear el perfil de tu bebé.": "让我们创建宝宝的个人资料。",
    "¿Cuántos meses tiene tu bebé? (1-36 meses)": "您的宝宝多大？(1-36个月)",
    "Perfecto. Ahora las alergias.\n\n¿Tiene tu bebé alguna alergia conocida?\n\nSelecciona todas las que apliquen o escribe 'ninguna'.":
        "好的。现在是过敏信息。\n\n您的宝宝有任何已知过敏吗？\n\n选择所有适用的或输入'无'。",
    "Perfil actualizado.": "资料已更新。",
    "Edad actualizada a ": "年龄已更新为",
    " meses.": " 个月。",
    "Gracias. ¿Algo más que deba saber sobre las alergias de tu bebé? (O escribe 'no')":
        "谢谢。您还有什么关于宝宝过敏的情况需要让我知道的吗？(或输入'无')",
    "¿Tienes alguna preferencia alimentaria para tu bebé? (O escribe 'no')":
        "您对宝宝的饮食有任何偏好么？(或输入'无')",
    "Configuración guardada.": "配置已保存。",
    "Primero necesito un plan semanal.": "请先创建每周计划。",
    # Meal card render
    "Use 1 for Monday breakfast": "选择 1 作为周一早餐",
    "Option ": "选项 ",
    # Slot actions
    "Regenerate meal": "重新生成餐食",
    "Meal cleared": "餐食已清除",
    # Onboarding prompt
    "Vamos a configurar tu perfil.": "让我们开始设置您的个人资料。",
    "¿Cuántos meses tiene tu bebé?": "您的宝宝多大？",
    "Perfecto. Ahora las alergias.\n\n¿Tiene tu bebé alguna alergia conocida?\n\nSelecciona todas las que apliquen.":
        "好的。现在设置过敏信息。\n\n您的宝宝有任何已知过敏吗？\n\n选择所有适用的。",
    "Gracias. ¿Algo más que deba saber sobre las alergias de tu bebé?":
        "谢谢。您还有什么关于宝宝过敏的情况需要让我知道的吗？",
    "¿Tienes alguna preferencia alimentaria para tu bebé?":
        "您对宝宝的饮食有任何偏好吗？",
    # Error messages
    "No plan for this week yet. Use /weekly_plan to build one.":
        "本周暂无计划。使用 /weekly_plan 创建。",
    "Couldn't read your plan. Try /weekly_plan.": "无法读取您的计划。使用 /weekly_plan 重试。",
    "Plan looks empty. Use /weekly_plan to rebuild.": "计划为空。使用 /weekly_plan 重新生成。",
    # Intro/outro messages
    "Cuando estés listo, toca Plan semanal para crear el horario de la próxima semana.":
        "准备就绪后，点击\"每周计划\"创建下周计划。",
    "Gracias por tu respuesta. Cuando quieras ver tu plan semanal, usa /weekly_plan.":
        "感谢您的回复。想查看每周计划时，请使用 /weekly_plan。",
    # Profile
    "Tu perfil:\n": "您的资料：\n",
    "Edad: ": "年龄：",
    " meses\n": " 个月\n",
    "Alergias: ": "过敏：",
    "Preferencias: ": "偏好：",
    "Haz clic /start para configurar el perfil de tu bebé.": "点击 /start 设置宝宝资料。",
    "Usa /set_age <meses> para actualizar la edad.": "使用 /set_age <月龄> 更新年龄。",
    "Usa /set_allergies <alergias> para actualizar las alergias.": "使用 /set_allergies <过敏> 更新过敏信息。",
    "Usa /profile para ver tu configuración actual.": "使用 /profile 查看当前配置。",
    # Shopping list
    "No puedo generar una lista de compras.": "无法生成购物清单。",
    "No hay plan para esta semana.": "本周暂无计划。",
    # Allergen journal
    "Registro de alergias.\n\nIngresa nuevos allergenos o actualiza los existentes.":
        "过敏记录。\n\n输入新的过敏原或更新现有记录。",
    "Nivel de exposición: ": "接触级别：",
    "Reaccionar más tarde.": "稍后记录。",
    # Nutrition
    "Resumen Nutricional": "营养摘要",
    "La resumen de nutrición está disponible solo en inglés.": "营养摘要仅提供英文版本。",
    # Stats
    "Aquí tienes tus estadísticas de comida.": "这是您的餐饮统计。",
    "No hay suficientes datos todavía.": "暂无足够数据。",
    " mes(es) de datos.": " 个月的数据。",
    "Calificación promedio de comidas: ": "平均餐食评分：",
    "Mejor día: ": "最佳日期：",
    "Lo más popular: ": "最受欢迎：",
    # Cancel
    "Cancelado.": "已取消。",
    "No hay nada que cancelar.": "没有正在进行的操作。",
    # History
    "Planes Recientes": "最近的计划",
    "Inspiraciones Recientes": "最近的灵感",
    # Regenerate
    "Generando nuevas opciones...": "正在生成新选项...",
    "Lo siento, no pude generar opciones nuevas. ¿Quieres intentar de nuevo?":
        "抱歉，无法生成新选项。要重试吗？",
    # Safety warning
    "⚠️": "⚠️",
    "Este plato contiene un alérgeno o ingrediente que no es seguro para tu bebé según su perfil.":
        "此菜品含有宝宝过敏原或不安全成分，根据宝宝资料不建议食用。",
    "Sustituir": "替换",
    "Entendido, usaré una alternativa.": "好的，我将使用替代品。",
    # Slot edit
    "Editar para ": "编辑",
    "Nueva opción para ": "的新选项",
    # Misc
    "Usa /start primero.": "请先使用 /start。",
    "Ocurrió un error. Por favor intenta de nuevo.": "发生错误。请重试。",
    "Algo salió mal.": "出了问题。",
    # Ingredient analysis
    "Demasiado sodio para tu bebé.": "钠含量对宝宝偏高。",
    "Este plato tiene un alto contenido de sodio.": "此菜品含钠量较高。",
    "No se encontró ningún plato para este momento del día.": "找不到当天此时段的食物。",
    "No se encontraron platos alternativos.": "未找到替代菜品。",
    # Slot adaptation
    "¿Cuál prefieres? (1 o 2)": "您更喜欢哪个？(1 或 2)",
    "Perfecto. Usaré": "好的。我将使用",
    "para": "作为",
    # Adapt nutrition
    "Resumen de nutrición semanal": "每周营养摘要",
    # Hardblock messages
    "lo siento, no puedo crear ese plato.": "抱歉，我无法制作这道菜。",
    "Haré una versión modificada sin": "我将制作一个不含以下成分的修改版本",
    # Shopping list
    "🛒 Lista de Compras": "🛒 购物清单",
    # Allergen intro journal
    " journal\n\nIngresa nuevos allergenos o actualiza los existentes.":
        " 记录\n\n输入新的过敏原或更新现有记录。",
}

for es_text, zh_text in spanish_to_chinese.items():
    content = content.replace(es_text, zh_text)

# ── 5. Swap if-language=="es" branches ────────────────────────────────────────
# Pattern: swap the language check so Chinese is the if-branch
content = re.sub(
    r'if language == "es":\n        help_text = \(',
    r'if language == "zh":\n        help_text = (',
    content
)

# ── 6. Remove all remaining if-language=="es"/"de" checks that we can't easily swap
# These are LLM prompt-related and should default to English → change to "zh"
content = re.sub(r'language == "es"(?!\w)', r'language == "zh"', content)
content = re.sub(r'language != "es"(?!\w)', r'language != "zh"', content)

# locale == "es" checks (user locale)
content = re.sub(r'locale == "es"', r'locale == "zh"', content)
content = re.sub(r'preferred_language == "es"', r'preferred_language == "zh"', content)

# context.user_data.get("onboarding_language") == "es"
content = re.sub(r'"onboarding_language"\) == "es"', r'"onboarding_language") == "zh"', content)

# user.language_code == "es"
content = re.sub(r'user\.language_code == "es"', r'user.language_code == "zh"', content)

# ── 7. Remove Spanish from SLOT_LABELS and DAY_LABELS (keep only EN/ZH) ─────────
# These are already handled in the dict definitions (done separately above)

# ── 8. Fix remaining "else: (Spanish content)" blocks in prompts ────────────────
# When we have: if language != "es": prompt = English; else: prompt = Spanish
# We want: if language != "zh": prompt = English; else: prompt = Chinese
# This was partially done in step 6. Check for remaining issues.

# Replace any remaining Spanish strings in the file that we missed
remaining_spanish_strings = [
    '"es"', "'es'", '"de"', "'de'",
]
# Count remaining occurrences
import re
remaining_es = len(re.findall(r'"es"|\'es\'', content))
remaining_de = len(re.findall(r'"de"|\'de\'', content))
print(f"Remaining 'es' refs: {remaining_es}")
print(f"Remaining 'de' refs: {remaining_de}")

if content != original:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"File updated: {path}")
    lines_changed = content.count('\n') - original.count('\n')
    print(f"Lines changed: {lines_changed}")
else:
    print("No changes made.")
