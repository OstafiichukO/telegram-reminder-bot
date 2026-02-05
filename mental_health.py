"""Mental health features: mood tracking, medications, breathing, CBT exercises."""

import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import database as db
import subscription as sub
import menu

# Mood emojis with scores
MOOD_OPTIONS = {
    "😢": {"score": 1, "label": "Дуже погано"},
    "😔": {"score": 2, "label": "Погано"},
    "😐": {"score": 3, "label": "Нормально"},
    "🙂": {"score": 4, "label": "Добре"},
    "😊": {"score": 5, "label": "Чудово"},
}

# Breathing exercises
BREATHING_EXERCISES = {
    "box": {
        "name": "Квадратне дихання",
        "description": "Техніка для заспокоєння та концентрації",
        "steps": [
            ("Вдих", 4),
            ("Затримка", 4),
            ("Видих", 4),
            ("Затримка", 4),
        ],
        "cycles": 4
    },
    "478": {
        "name": "Дихання 4-7-8",
        "description": "Техніка для швидкого розслаблення та сну",
        "steps": [
            ("Вдих", 4),
            ("Затримка", 7),
            ("Видих", 8),
        ],
        "cycles": 4
    },
    "calm": {
        "name": "Заспокійливе дихання",
        "description": "Простa техніка для зняття стресу",
        "steps": [
            ("Вдих", 4),
            ("Видих", 6),
        ],
        "cycles": 6
    }
}

# CBT exercises
CBT_EXERCISES = {
    "thoughts": {
        "name": "🧠 Аналіз думок",
        "description": "Визначте та проаналізуйте негативні думки",
        "questions": [
            "Яка думка вас турбує зараз?",
            "Які докази ЗА цю думку?",
            "Які докази ПРОТИ цієї думки?",
            "Як би ви порадили другу в такій ситуації?",
            "Яка більш збалансована думка?"
        ]
    },
    "gratitude": {
        "name": "🙏 Вдячність",
        "description": "Запишіть 3 речі, за які ви вдячні сьогодні",
        "questions": [
            "За що ви вдячні сьогодні? (1/3)",
            "Друга річ, за яку вдячні:",
            "Третя річ:"
        ]
    },
    "reframe": {
        "name": "🔄 Переосмислення",
        "description": "Перетворіть негативну ситуацію на можливість",
        "questions": [
            "Опишіть ситуацію, яка вас засмучує:",
            "Чого ця ситуація може вас навчити?",
            "Як ви можете вирости завдяки цьому?"
        ]
    }
}

# Conversation states for mental health features
MED_NAME, MED_DOSAGE, MED_TIME = range(100, 103)
CBT_EXERCISE = range(200, 201)[0]


# ============ MOOD TRACKING ============

async def mood_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start mood tracking."""
    user_id = update.effective_user.id
    
    # Check mood limit
    allowed, limit_msg = sub.check_limit(user_id, "mood_per_day")
    if not allowed:
        await update.message.reply_text(limit_msg, parse_mode="Markdown")
        return
    
    keyboard = [
        [InlineKeyboardButton(f"{emoji} {data['label']}", callback_data=f"mood_{emoji}")]
        for emoji, data in MOOD_OPTIONS.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎭 *Як ви себе почуваєте зараз?*\n\n"
        "Оберіть варіант, який найкраще описує ваш настрій:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def handle_mood_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle mood emoji selection."""
    query = update.callback_query
    await query.answer()
    
    emoji = query.data.replace("mood_", "")
    mood_data = MOOD_OPTIONS.get(emoji)
    
    if not mood_data:
        return
    
    user_id = query.from_user.id
    
    # Save mood entry
    db.add_mood_entry(user_id, mood_data["score"], emoji)
    
    # Get stats
    stats = db.get_mood_stats(user_id, days=7)
    
    response = f"✅ Записано: {emoji} {mood_data['label']}\n\n"
    
    if stats["count"] > 1:
        response += f"📊 *Статистика за 7 днів:*\n"
        response += f"• Середній настрій: {stats['average']}/5\n"
        response += f"• Записів: {stats['count']}\n"
    
    # Add encouraging message based on mood
    if mood_data["score"] <= 2:
        response += "\n💙 Пам'ятайте: погані дні бувають у всіх. "
        response += "Спробуйте «🫁 Дихання» для заспокоєння."
    elif mood_data["score"] >= 4:
        response += "\n🌟 Чудово! Продовжуйте в тому ж дусі!"
    
    await query.edit_message_text(response, parse_mode="Markdown")
    
    # Send menu
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Оберіть функцію:",
        reply_markup=menu.get_health_menu()
    )


async def mood_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show mood statistics."""
    user_id = update.effective_user.id
    
    # Get recent entries
    entries = db.get_mood_history(user_id, days=7)
    stats = db.get_mood_stats(user_id, days=30)
    
    if not entries:
        await update.message.reply_text(
            "📊 У вас ще немає записів настрою.\n\n"
            "Натисніть «🎭 Настрій» щоб почати відстежувати!",
            reply_markup=menu.get_health_menu()
        )
        return
    
    # Build stats message
    message = "📊 *Статистика настрою*\n\n"
    
    # 30-day stats
    message += f"*За останні 30 днів:*\n"
    message += f"• Середній настрій: {stats['average']}/5\n"
    message += f"• Найнижчий: {stats['min']}/5\n"
    message += f"• Найвищий: {stats['max']}/5\n"
    message += f"• Всього записів: {stats['count']}\n\n"
    
    # Recent history
    message += "*Останні записи:*\n"
    for score, emoji, note, created_at in entries[:7]:
        date = datetime.fromisoformat(created_at).strftime("%d.%m %H:%M")
        message += f"{emoji} {date}"
        if note:
            message += f" - {note[:30]}..."
        message += "\n"
    
    # Mood trend visualization
    if len(entries) >= 3:
        message += "\n*Тренд:* "
        recent_scores = [e[0] for e in entries[:5]]
        avg_recent = sum(recent_scores) / len(recent_scores)
        if avg_recent >= 4:
            message += "📈 Позитивний!"
        elif avg_recent >= 3:
            message += "➡️ Стабільний"
        else:
            message += "📉 Потребує уваги"
    
    await update.message.reply_text(
        message, 
        parse_mode="Markdown",
        reply_markup=menu.get_health_menu()
    )


# ============ BREATHING EXERCISES ============

async def breathe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show breathing exercises menu."""
    keyboard = [
        [InlineKeyboardButton(
            f"{ex['name']}", 
            callback_data=f"breathe_{key}"
        )]
        for key, ex in BREATHING_EXERCISES.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🫁 *Дихальні вправи*\n\n"
        "Оберіть техніку дихання:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def handle_breathing_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a breathing exercise."""
    query = update.callback_query
    await query.answer()
    
    exercise_key = query.data.replace("breathe_", "")
    exercise = BREATHING_EXERCISES.get(exercise_key)
    
    if not exercise:
        return
    
    # Show exercise info
    await query.edit_message_text(
        f"🫁 *{exercise['name']}*\n\n"
        f"{exercise['description']}\n\n"
        f"Вправа почнеться через 3 секунди...\n"
        f"Знайдіть зручне положення та розслабтесь.",
        parse_mode="Markdown"
    )
    
    await asyncio.sleep(3)
    
    # Run breathing cycles
    for cycle in range(1, exercise["cycles"] + 1):
        for step_name, duration in exercise["steps"]:
            # Show step
            if step_name == "Вдих":
                emoji = "🌬️"
            elif step_name == "Видих":
                emoji = "💨"
            else:
                emoji = "⏸️"
            
            await query.edit_message_text(
                f"🫁 *{exercise['name']}*\n\n"
                f"Цикл {cycle}/{exercise['cycles']}\n\n"
                f"{emoji} *{step_name}*\n"
                f"{'⬜' * duration}\n\n"
                f"_{duration} секунд_",
                parse_mode="Markdown"
            )
            
            # Countdown
            for i in range(duration, 0, -1):
                await asyncio.sleep(1)
                filled = duration - i
                empty = i
                progress = '⬛' * filled + '⬜' * empty
                
                try:
                    await query.edit_message_text(
                        f"🫁 *{exercise['name']}*\n\n"
                        f"Цикл {cycle}/{exercise['cycles']}\n\n"
                        f"{emoji} *{step_name}*\n"
                        f"{progress}\n\n"
                        f"_{i} сек_",
                        parse_mode="Markdown"
                    )
                except:
                    pass  # Ignore rate limit errors
    
    # Completion message
    await query.edit_message_text(
        f"✅ *Вправу завершено!*\n\n"
        f"🫁 {exercise['name']}\n"
        f"Ви виконали {exercise['cycles']} циклів.\n\n"
        f"Як ви себе почуваєте? Натисніть «🎭 Настрій»",
        parse_mode="Markdown"
    )
    
    # Send menu
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Оберіть функцію:",
        reply_markup=menu.get_health_menu()
    )


# ============ CBT EXERCISES ============

async def cbt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show CBT exercises menu."""
    keyboard = [
        [InlineKeyboardButton(
            ex["name"],
            callback_data=f"cbt_{key}"
        )]
        for key, ex in CBT_EXERCISES.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🧠 *Когнітивні вправи (CBT)*\n\n"
        "Ці техніки допомагають працювати з думками та емоціями.\n\n"
        "Оберіть вправу:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def handle_cbt_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a CBT exercise."""
    query = update.callback_query
    await query.answer()
    
    exercise_key = query.data.replace("cbt_", "")
    exercise = CBT_EXERCISES.get(exercise_key)
    
    if not exercise:
        return
    
    # Store exercise state
    context.user_data["cbt_exercise"] = exercise_key
    context.user_data["cbt_step"] = 0
    context.user_data["cbt_answers"] = []
    
    await query.edit_message_text(
        f"{exercise['name']}\n\n"
        f"_{exercise['description']}_\n\n"
        f"*Питання 1/{len(exercise['questions'])}:*\n"
        f"{exercise['questions'][0]}",
        parse_mode="Markdown"
    )
    
    return CBT_EXERCISE


async def handle_cbt_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle CBT exercise answers."""
    if "cbt_exercise" not in context.user_data:
        return ConversationHandler.END
    
    exercise_key = context.user_data["cbt_exercise"]
    exercise = CBT_EXERCISES.get(exercise_key)
    step = context.user_data.get("cbt_step", 0)
    answers = context.user_data.get("cbt_answers", [])
    
    # Save answer
    answers.append(update.message.text)
    context.user_data["cbt_answers"] = answers
    
    # Move to next question
    step += 1
    context.user_data["cbt_step"] = step
    
    if step < len(exercise["questions"]):
        # Ask next question
        await update.message.reply_text(
            f"*Питання {step + 1}/{len(exercise['questions'])}:*\n"
            f"{exercise['questions'][step]}",
            parse_mode="Markdown"
        )
        return CBT_EXERCISE
    else:
        # Exercise complete - show summary
        summary = f"✅ *Вправу завершено!*\n\n"
        summary += f"{exercise['name']}\n\n"
        
        for i, (q, a) in enumerate(zip(exercise["questions"], answers)):
            summary += f"*{i+1}. {q}*\n"
            summary += f"_{a}_\n\n"
        
        summary += "💙 Чудова робота! Регулярна практика допомагає покращити ментальне здоров'я."
        
        await update.message.reply_text(
            summary, 
            parse_mode="Markdown",
            reply_markup=menu.get_health_menu()
        )
        
        # Clean up
        context.user_data.pop("cbt_exercise", None)
        context.user_data.pop("cbt_step", None)
        context.user_data.pop("cbt_answers", None)
        
        return ConversationHandler.END


# ============ MEDICATIONS ============

async def meds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show medications menu."""
    user_id = update.effective_user.id
    meds = db.get_user_medications(user_id)
    
    keyboard = [
        [InlineKeyboardButton("➕ Додати ліки", callback_data="meds_add")],
    ]
    
    if meds:
        keyboard.append([InlineKeyboardButton("📋 Мої ліки", callback_data="meds_list")])
        keyboard.append([InlineKeyboardButton("📊 Статистика", callback_data="meds_stats")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "💊 *Нагадування про ліки*\n\n"
        "Я допоможу вам не пропускати прийом ліків.\n\n"
        "Оберіть дію:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def handle_meds_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle medication menu callbacks."""
    query = update.callback_query
    await query.answer()
    
    action = query.data.replace("meds_", "")
    user_id = query.from_user.id
    
    if action == "add":
        user_id = query.from_user.id
        
        # Check medication limit
        allowed, limit_msg = sub.check_limit(user_id, "medications")
        if not allowed:
            await query.edit_message_text(limit_msg, parse_mode="Markdown")
            return ConversationHandler.END
        
        await query.edit_message_text(
            "💊 *Додавання ліків*\n\n"
            "Введіть назву препарату:",
            parse_mode="Markdown"
        )
        return MED_NAME
    
    elif action == "list":
        meds = db.get_user_medications(user_id)
        
        if not meds:
            await query.edit_message_text("📭 У вас немає активних нагадувань про ліки.")
            return
        
        message = "💊 *Ваші ліки:*\n\n"
        for med_id, name, dosage, schedule_time, repeat_type in meds:
            message += f"• *{name}*"
            if dosage:
                message += f" ({dosage})"
            message += f"\n  ⏰ {schedule_time}\n"
        
        keyboard = [[InlineKeyboardButton("🗑 Видалити", callback_data="meds_delete")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="Markdown")
    
    elif action == "stats":
        stats = db.get_medication_adherence(user_id, days=7)
        
        message = "📊 *Статистика за 7 днів:*\n\n"
        message += f"✅ Прийнято: {stats['taken']}\n"
        message += f"⏭ Пропущено: {stats['skipped']}\n"
        message += f"❌ Забуто: {stats['missed']}\n\n"
        message += f"📈 Дотримання: *{stats['adherence_rate']}%*"
        
        await query.edit_message_text(message, parse_mode="Markdown")
    
    elif action == "delete":
        meds = db.get_user_medications(user_id)
        
        keyboard = [
            [InlineKeyboardButton(f"🗑 {name}", callback_data=f"meds_del_{med_id}")]
            for med_id, name, _, _, _ in meds
        ]
        keyboard.append([InlineKeyboardButton("❌ Скасувати", callback_data="meds_cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "Оберіть ліки для видалення:",
            reply_markup=reply_markup
        )
    
    elif action.startswith("del_"):
        med_id = int(action.replace("del_", ""))
        db.delete_medication(med_id, user_id)
        await query.edit_message_text("✅ Ліки видалено!")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Оберіть функцію:",
            reply_markup=menu.get_health_menu()
        )
    
    elif action == "cancel":
        await query.edit_message_text("❌ Скасовано.")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Оберіть функцію:",
            reply_markup=menu.get_health_menu()
        )
    
    return ConversationHandler.END


async def handle_med_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle medication name input."""
    context.user_data["med_name"] = update.message.text
    
    await update.message.reply_text(
        "💊 Введіть дозування (або напишіть 'пропустити'):\n\n"
        "Наприклад: `1 таблетка`, `5мг`, `2 капсули`",
        parse_mode="Markdown"
    )
    return MED_DOSAGE


async def handle_med_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle medication dosage input."""
    dosage = update.message.text
    if dosage.lower() == "пропустити":
        dosage = None
    context.user_data["med_dosage"] = dosage
    
    await update.message.reply_text(
        "⏰ Введіть час прийому:\n\n"
        "Формат: `ГГ:ХХ`\n"
        "Наприклад: `09:00` або `21:30`",
        parse_mode="Markdown"
    )
    return MED_TIME


async def handle_med_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle medication time input."""
    time_text = update.message.text.strip()
    
    try:
        # Validate time format
        datetime.strptime(time_text, "%H:%M")
    except ValueError:
        await update.message.reply_text(
            "❌ Невірний формат часу! Використовуйте ГГ:ХХ\n"
            "Спробуйте ще раз:"
        )
        return MED_TIME
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Save medication
    med_id = db.add_medication(
        user_id=user_id,
        chat_id=chat_id,
        name=context.user_data["med_name"],
        dosage=context.user_data.get("med_dosage"),
        schedule_time=time_text
    )
    
    await update.message.reply_text(
        f"✅ *Нагадування створено!*\n\n"
        f"💊 {context.user_data['med_name']}\n"
        f"📦 {context.user_data.get('med_dosage') or 'Не вказано'}\n"
        f"⏰ Щодня о {time_text}\n\n"
        f"Я нагадуватиму вам про прийом!",
        parse_mode="Markdown",
        reply_markup=menu.get_health_menu()
    )
    
    # Clear user data
    context.user_data.pop("med_name", None)
    context.user_data.pop("med_dosage", None)
    
    return ConversationHandler.END


async def handle_med_taken(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle medication taken/skipped confirmation."""
    query = update.callback_query
    await query.answer()
    
    data = query.data  # format: med_taken_ID or med_skip_ID
    parts = data.split("_")
    action = parts[1]  # taken or skip
    med_id = int(parts[2])
    user_id = query.from_user.id
    
    status = "taken" if action == "taken" else "skipped"
    db.log_medication_taken(med_id, user_id, status)
    
    med = db.get_medication_by_id(med_id)
    
    if action == "taken":
        await query.edit_message_text(
            f"✅ Чудово! Ви прийняли *{med[3]}*\n\n"
            f"Продовжуйте дотримуватись графіку! 💪",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            f"⏭ Пропущено: *{med[3]}*\n\n"
            f"Не забудьте проконсультуватися з лікарем, якщо часто пропускаєте.",
            parse_mode="Markdown"
        )
    
    # Send menu
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Оберіть функцію:",
        reply_markup=menu.get_health_menu()
    )
