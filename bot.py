import os
import json
import logging
from datetime import datetime, timedelta
from threading import Thread
from dotenv import load_dotenv
from http.server import HTTPServer, BaseHTTPRequestHandler

from openai import AsyncOpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

import database as db
import scheduler
import mental_health as mh
import subscription as sub
import menu

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# OpenAI client
openai_client = None
if os.getenv("OPENAI_API_KEY"):
    openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Store conversation history per user
chat_history: dict[int, list] = {}

# Store pending reminders awaiting confirmation
pending_reminders: dict[int, dict] = {}

# Track daily AI message counts per user (resets daily)
ai_message_counts: dict[int, dict] = {}  # {user_id: {"date": "2024-01-01", "count": 5}}

# Conversation states
TITLE, TIME, REPEAT = range(3)

# Repeat options
REPEAT_OPTIONS = {
    "once": "Один раз",
    "hourly": "Щогодини",
    "daily": "Щодня",
    "weekly": "Щотижня",
    "monthly": "Щомісяця",
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message when /start is issued."""
    user = update.effective_user
    
    # Initialize user settings
    settings = db.get_or_create_user_settings(user.id)
    is_premium = db.is_premium(user.id)
    
    gpt_status = "✅" if openai_client else "❌"
    sub_status = "⭐ Premium" if is_premium else "Free"
    
    welcome_text = f"""
👋 Привіт, {user.first_name}!

Я ваш персональний асистент для ментального здоров'я та продуктивності.

📊 Ваш план: *{sub_status}*

*Використовуйте меню нижче* для швидкого доступу до функцій або просто напишіть мені!

🤖 AI-асистент: {gpt_status}

Напишіть "нагадай мені..." і я створю нагадування автоматично!
"""
    await update.message.reply_text(
        welcome_text, 
        parse_mode="Markdown",
        reply_markup=menu.get_main_menu()
    )


async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle menu button presses. Returns True if handled."""
    text = update.message.text
    
    if text not in menu.MENU_COMMANDS:
        return False  # Not a menu button
    
    action = menu.MENU_COMMANDS[text]
    
    # Handle submenu navigation
    if action == "menu_reminders":
        await update.message.reply_text(
            "📝 *Нагадування*\n\nОберіть дію:",
            parse_mode="Markdown",
            reply_markup=menu.get_reminders_menu()
        )
        return True
    
    elif action == "menu_health":
        await update.message.reply_text(
            "💚 *Ментальне здоров'я*\n\nОберіть функцію:",
            parse_mode="Markdown",
            reply_markup=menu.get_health_menu()
        )
        return True
    
    elif action == "menu_settings":
        await update.message.reply_text(
            "⚙️ *Налаштування*\n\nОберіть опцію:",
            parse_mode="Markdown",
            reply_markup=menu.get_settings_menu()
        )
        return True
    
    elif action == "menu_main":
        await update.message.reply_text(
            "🏠 *Головне меню*",
            parse_mode="Markdown",
            reply_markup=menu.get_main_menu()
        )
        return True
    
    elif action == "menu_ai":
        await update.message.reply_text(
            "🤖 *AI Чат*\n\n"
            "Просто напишіть мені що завгодно!\n\n"
            "Наприклад:\n"
            "• «Нагадай завтра о 9 про зустріч»\n"
            "• «Як покращити сон?»\n"
            "• «Порадь дихальну вправу»",
            parse_mode="Markdown",
            reply_markup=menu.get_main_menu()
        )
        return True
    
    # Handle command shortcuts - call functions directly
    elif action == "/add":
        result = await add_reminder_start(update, context)
        if result is not None:
            context.user_data["conversation_state"] = "add_reminder"
            context.user_data["conversation_step"] = result
        return True
    
    elif action == "/list":
        await list_reminders(update, context)
        return True
    
    elif action == "/delete":
        result = await delete_reminder_start(update, context)
        if result is not None and result != ConversationHandler.END:
            context.user_data["conversation_state"] = "delete_reminder"
        return True
    
    elif action == "/mood":
        await mh.mood_command(update, context)
        return True
    
    elif action == "/moodstats":
        await mh.mood_stats_command(update, context)
        return True
    
    elif action == "/breathe":
        await mh.breathe_command(update, context)
        return True
    
    elif action == "/cbt":
        await mh.cbt_command(update, context)
        return True
    
    elif action == "/meds":
        await mh.meds_command(update, context)
        return True
    
    elif action == "/subscription":
        await sub.subscription_command(update, context)
        return True
    
    elif action == "/timezone":
        await timezone_command(update, context)
        return True
    
    elif action == "/help":
        await help_command(update, context)
        return True
    
    return False


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message."""
    help_text = """
📚 *Довідка*

*📝 Нагадування:*
/add - Створити нагадування
/list - Переглянути всі
/delete - Видалити
/cancel - Скасувати дію

*💚 Ментальне здоров'я:*
/mood - Записати настрій (1-5)
/moodstats - Статистика настрою
/breathe - Дихальні вправи
/cbt - Когнітивні вправи (CBT)
/meds - Нагадування про ліки

*🤖 AI-асистент:*
Просто напишіть повідомлення!
Наприклад: "Нагадай завтра о 9 про зустріч"
/clear - Очистити історію чату

*⏰ Формат часу:*
`25.12.2025 14:30` або `14:30`

*🔄 Повторення:*
Один раз • Щогодини • Щодня • Щотижня • Щомісяця

*💡 Поради:*
• Записуйте настрій щодня для кращого розуміння себе
• Використовуйте дихальні вправи при стресі
• AI може створювати нагадування з контексту
"""
    await update.message.reply_text(
        help_text, 
        parse_mode="Markdown",
        reply_markup=menu.get_main_menu()
    )


async def clear_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear chat history with AI."""
    user_id = update.effective_user.id
    if user_id in chat_history:
        chat_history[user_id] = []
    await update.message.reply_text("🗑 Історію чату очищено!")


def check_ai_limit(user_id: int) -> tuple[bool, str]:
    """Check if user can send AI message."""
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Get or create user's counter
    if user_id not in ai_message_counts:
        ai_message_counts[user_id] = {"date": today, "count": 0}
    
    user_counter = ai_message_counts[user_id]
    
    # Reset if new day
    if user_counter["date"] != today:
        user_counter["date"] = today
        user_counter["count"] = 0
    
    # Check limit
    limits = db.get_user_limits(user_id)
    limit = limits.get("ai_messages_per_day", 10)
    
    if user_counter["count"] >= limit:
        return False, (
            f"⚠️ *Ліміт AI-повідомлень вичерпано!*\n\n"
            f"Використано: {user_counter['count']}/{limit} на сьогодні\n\n"
            f"⭐ Оновіть до Premium для безлімітного AI!\n"
            f"Використайте /subscription"
        )
    
    return True, ""


def increment_ai_count(user_id: int):
    """Increment AI message count for user."""
    today = datetime.now().strftime("%Y-%m-%d")
    
    if user_id not in ai_message_counts:
        ai_message_counts[user_id] = {"date": today, "count": 0}
    
    if ai_message_counts[user_id]["date"] != today:
        ai_message_counts[user_id] = {"date": today, "count": 0}
    
    ai_message_counts[user_id]["count"] += 1


async def chat_with_gpt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular messages with ChatGPT."""
    if not openai_client:
        await update.message.reply_text(
            "⚠️ ChatGPT не налаштовано. Додайте OPENAI_API_KEY."
        )
        return
    
    user_id = update.effective_user.id
    user_message = update.message.text
    
    # Check AI message limit
    allowed, limit_msg = check_ai_limit(user_id)
    if not allowed:
        await update.message.reply_text(limit_msg, parse_mode="Markdown")
        return
    
    # Initialize history for new users
    if user_id not in chat_history:
        chat_history[user_id] = []
    
    # Add user message to history
    chat_history[user_id].append({
        "role": "user",
        "content": user_message
    })
    
    # Keep only last 20 messages to save tokens
    if len(chat_history[user_id]) > 20:
        chat_history[user_id] = chat_history[user_id][-20:]
    
    # Show typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )
    
    # Get current date/time for context
    now = datetime.now()
    current_datetime = now.strftime("%d.%m.%Y %H:%M")
    current_weekday = ["понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя"][now.weekday()]
    
    system_prompt = f"""Ти корисний асистент з функцією створення нагадувань. Відповідай українською мовою.

Поточна дата і час: {current_datetime} ({current_weekday})

ВАЖЛИВО: Якщо користувач хоче створити нагадування (наприклад: "нагадай мені...", "створи нагадування...", "не забути...", "через годину нагадай...", тощо), ти ПОВИНЕН відповісти ТІЛЬКИ валідним JSON об'єктом без додаткового тексту:

{{
    "is_reminder": true,
    "title": "короткий опис нагадування",
    "datetime": "ДД.ММ.РРРР ГГ:ХХ",
    "repeat": "once|hourly|daily|weekly|monthly",
    "message": "дружнє підтвердження українською"
}}

Правила для datetime:
- "завтра о 9" = завтрашня дата о 09:00
- "через годину" = поточний час + 1 година
- "через 30 хвилин" = поточний час + 30 хвилин
- "в понеділок о 10" = найближчий понеділок о 10:00
- "щодня о 8 ранку" = завтра о 08:00, repeat: "daily"

Правила для repeat:
- За замовчуванням "once" (один раз)
- "щодня", "кожен день" = "daily"
- "щотижня", "кожен тиждень" = "weekly"  
- "щомісяця" = "monthly"
- "щогодини" = "hourly"

Якщо це НЕ запит на нагадування, просто відповідай як звичайний асистент (без JSON)."""

    try:
        # Call ChatGPT
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                *chat_history[user_id]
            ],
            max_tokens=1000
        )
        
        assistant_message = response.choices[0].message.content.strip()
        
        # Try to parse as reminder JSON
        try:
            # Check if response looks like JSON
            if assistant_message.startswith("{") and "is_reminder" in assistant_message:
                reminder_data = json.loads(assistant_message)
                
                if reminder_data.get("is_reminder"):
                    # Parse the datetime
                    reminder_time = datetime.strptime(
                        reminder_data["datetime"], 
                        "%d.%m.%Y %H:%M"
                    )
                    
                    # Validate time is in future
                    if reminder_time <= datetime.now():
                        await update.message.reply_text(
                            "❌ Вказаний час вже минув. Спробуйте ще раз з майбутнім часом."
                        )
                        return
                    
                    # Store pending reminder
                    pending_reminders[user_id] = {
                        "title": reminder_data["title"],
                        "datetime": reminder_time,
                        "repeat": reminder_data.get("repeat", "once"),
                        "chat_id": update.effective_chat.id
                    }
                    
                    # Format confirmation message
                    time_str = reminder_time.strftime("%d.%m.%Y о %H:%M")
                    repeat_label = REPEAT_OPTIONS.get(
                        reminder_data.get("repeat", "once"), 
                        "Один раз"
                    )
                    
                    confirm_message = f"""🔔 *Створити нагадування?*

📌 *Назва:* {reminder_data["title"]}
⏰ *Час:* {time_str}
🔄 *Повторення:* {repeat_label}

{reminder_data.get("message", "")}"""
                    
                    # Create confirmation buttons
                    keyboard = [
                        [
                            InlineKeyboardButton("✅ Створити", callback_data="ai_confirm"),
                            InlineKeyboardButton("❌ Скасувати", callback_data="ai_cancel")
                        ],
                        [
                            InlineKeyboardButton("✏️ Змінити час", callback_data="ai_edit_time"),
                            InlineKeyboardButton("🔄 Змінити повторення", callback_data="ai_edit_repeat")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        confirm_message,
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                    
                    # Add to history for context
                    chat_history[user_id].append({
                        "role": "assistant",
                        "content": f"Запропоновано створити нагадування: {reminder_data['title']} на {time_str}"
                    })
                    return
                    
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Not a valid reminder JSON, treat as regular message
            logger.debug(f"Not a reminder response: {e}")
        
        # Regular chat response
        chat_history[user_id].append({
            "role": "assistant",
            "content": assistant_message
        })
        
        # Increment AI message count
        increment_ai_count(user_id)
        
        await update.message.reply_text(assistant_message)
        
    except Exception as e:
        logger.error(f"ChatGPT error: {e}")
        await update.message.reply_text(
            "❌ Помилка при зверненні до ChatGPT. Спробуйте пізніше."
        )


async def handle_ai_reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle AI reminder confirmation callbacks."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    action = query.data
    
    if action == "ai_confirm":
        # Create the reminder
        if user_id not in pending_reminders:
            await query.edit_message_text("❌ Нагадування не знайдено. Спробуйте ще раз.")
            return
        
        reminder = pending_reminders[user_id]
        
        # Save to database
        reminder_id = db.add_reminder(
            user_id=user_id,
            chat_id=reminder["chat_id"],
            title=reminder["title"],
            reminder_time=reminder["datetime"],
            repeat_type=reminder["repeat"]
        )
        
        # Schedule the reminder
        bot = context.application.bot
        scheduler.schedule_reminder(bot, reminder_id, reminder["datetime"])
        
        # Format confirmation
        time_str = reminder["datetime"].strftime("%d.%m.%Y о %H:%M")
        repeat_label = REPEAT_OPTIONS.get(reminder["repeat"], "Один раз")
        
        await query.edit_message_text(
            f"✅ *Нагадування створено!*\n\n"
            f"📌 *Назва:* {reminder['title']}\n"
            f"⏰ *Час:* {time_str}\n"
            f"🔄 *Повторення:* {repeat_label}",
            parse_mode="Markdown"
        )
        
        # Send menu
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Що далі?",
            reply_markup=menu.get_main_menu()
        )
        
        # Clean up
        del pending_reminders[user_id]
        
    elif action == "ai_cancel":
        if user_id in pending_reminders:
            del pending_reminders[user_id]
        await query.edit_message_text("❌ Створення нагадування скасовано.")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Що далі?",
            reply_markup=menu.get_main_menu()
        )
        
    elif action == "ai_edit_time":
        await query.edit_message_text(
            "⏰ Введіть новий час у форматі:\n\n"
            "`ДД.ММ.РРРР ГГ:ХХ` або `ГГ:ХХ`\n\n"
            "Наприклад: `25.12.2025 14:30` або `14:30`",
            parse_mode="Markdown"
        )
        # Store state for editing
        context.user_data["editing_ai_reminder"] = "time"
        
    elif action == "ai_edit_repeat":
        if user_id not in pending_reminders:
            await query.edit_message_text("❌ Нагадування не знайдено.")
            return
            
        keyboard = [
            [InlineKeyboardButton(label, callback_data=f"ai_repeat_{key}")]
            for key, label in REPEAT_OPTIONS.items()
        ]
        keyboard.append([InlineKeyboardButton("❌ Скасувати", callback_data="ai_cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🔄 Оберіть частоту повторення:",
            reply_markup=reply_markup
        )


async def handle_ai_repeat_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle repeat type selection for AI reminder."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    repeat_type = query.data.replace("ai_repeat_", "")
    
    if user_id not in pending_reminders:
        await query.edit_message_text("❌ Нагадування не знайдено.")
        return
    
    # Update repeat type
    pending_reminders[user_id]["repeat"] = repeat_type
    
    # Show updated confirmation
    reminder = pending_reminders[user_id]
    time_str = reminder["datetime"].strftime("%d.%m.%Y о %H:%M")
    repeat_label = REPEAT_OPTIONS.get(repeat_type, "Один раз")
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Створити", callback_data="ai_confirm"),
            InlineKeyboardButton("❌ Скасувати", callback_data="ai_cancel")
        ],
        [
            InlineKeyboardButton("✏️ Змінити час", callback_data="ai_edit_time"),
            InlineKeyboardButton("🔄 Змінити повторення", callback_data="ai_edit_repeat")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🔔 *Створити нагадування?*\n\n"
        f"📌 *Назва:* {reminder['title']}\n"
        f"⏰ *Час:* {time_str}\n"
        f"🔄 *Повторення:* {repeat_label}",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def handle_ai_time_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle time edit for AI reminder."""
    if context.user_data.get("editing_ai_reminder") != "time":
        return False
    
    user_id = update.effective_user.id
    time_text = update.message.text.strip()
    
    if user_id not in pending_reminders:
        await update.message.reply_text("❌ Нагадування не знайдено. Почніть спочатку.")
        context.user_data.pop("editing_ai_reminder", None)
        return True
    
    try:
        # Parse time
        if " " in time_text:
            reminder_time = datetime.strptime(time_text, "%d.%m.%Y %H:%M")
        else:
            time_only = datetime.strptime(time_text, "%H:%M")
            today = datetime.now()
            reminder_time = today.replace(
                hour=time_only.hour,
                minute=time_only.minute,
                second=0,
                microsecond=0
            )
            if reminder_time <= datetime.now():
                reminder_time += timedelta(days=1)
        
        if reminder_time <= datetime.now():
            await update.message.reply_text(
                "❌ Час повинен бути у майбутньому! Спробуйте ще раз:"
            )
            return True
        
        # Update time
        pending_reminders[user_id]["datetime"] = reminder_time
        context.user_data.pop("editing_ai_reminder", None)
        
        # Show updated confirmation
        reminder = pending_reminders[user_id]
        time_str = reminder_time.strftime("%d.%m.%Y о %H:%M")
        repeat_label = REPEAT_OPTIONS.get(reminder["repeat"], "Один раз")
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Створити", callback_data="ai_confirm"),
                InlineKeyboardButton("❌ Скасувати", callback_data="ai_cancel")
            ],
            [
                InlineKeyboardButton("✏️ Змінити час", callback_data="ai_edit_time"),
                InlineKeyboardButton("🔄 Змінити повторення", callback_data="ai_edit_repeat")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🔔 *Створити нагадування?*\n\n"
            f"📌 *Назва:* {reminder['title']}\n"
            f"⏰ *Час:* {time_str}\n"
            f"🔄 *Повторення:* {repeat_label}",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return True
        
    except ValueError:
        await update.message.reply_text(
            "❌ Невірний формат часу!\n\n"
            "Використовуйте: `ДД.ММ.РРРР ГГ:ХХ` або `ГГ:ХХ`",
            parse_mode="Markdown"
        )
        return True


async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show timezone settings (placeholder)."""
    await update.message.reply_text(
        "🌍 *Часовий пояс*\n\n"
        "Поточний: Europe/Kyiv (UTC+2)\n\n"
        "_Функція зміни часового поясу буде доступна незабаром._",
        parse_mode="Markdown",
        reply_markup=menu.get_main_menu()
    )


async def add_reminder_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the add reminder conversation."""
    user_id = update.effective_user.id
    
    # Check reminder limit
    allowed, limit_msg = sub.check_limit(user_id, "reminders")
    if not allowed:
        await update.message.reply_text(limit_msg, parse_mode="Markdown")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "📝 *Створення нагадування*\n\n"
        "Введіть назву нагадування:",
        parse_mode="Markdown"
    )
    return TITLE


async def add_reminder_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle reminder title input."""
    context.user_data["reminder_title"] = update.message.text
    
    await update.message.reply_text(
        "⏰ Введіть дату і час нагадування:\n\n"
        "Формат: `ДД.ММ.РРРР ГГ:ХХ`\n"
        "Наприклад: `25.12.2025 14:30`\n\n"
        "Або тільки час для сьогодні: `14:30`",
        parse_mode="Markdown"
    )
    return TIME


async def add_reminder_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle reminder time input."""
    time_text = update.message.text.strip()
    
    try:
        # Try full datetime format
        if " " in time_text:
            reminder_time = datetime.strptime(time_text, "%d.%m.%Y %H:%M")
        else:
            # Only time provided - use today's date
            time_only = datetime.strptime(time_text, "%H:%M")
            today = datetime.now()
            reminder_time = today.replace(
                hour=time_only.hour,
                minute=time_only.minute,
                second=0,
                microsecond=0
            )
            # If time has passed today, schedule for tomorrow
            if reminder_time <= datetime.now():
                from datetime import timedelta
                reminder_time += timedelta(days=1)
        
        if reminder_time <= datetime.now():
            await update.message.reply_text(
                "❌ Час повинен бути у майбутньому!\n"
                "Спробуйте ще раз:"
            )
            return TIME
        
        context.user_data["reminder_time"] = reminder_time
        
        # Show repeat options
        keyboard = [
            [InlineKeyboardButton(label, callback_data=f"repeat_{key}")]
            for key, label in REPEAT_OPTIONS.items()
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🔄 Оберіть частоту повторення:",
            reply_markup=reply_markup
        )
        return REPEAT
        
    except ValueError:
        await update.message.reply_text(
            "❌ Невірний формат часу!\n\n"
            "Використовуйте:\n"
            "• `ДД.ММ.РРРР ГГ:ХХ` (наприклад: `25.12.2025 14:30`)\n"
            "• `ГГ:ХХ` для сьогодні (наприклад: `14:30`)\n\n"
            "Спробуйте ще раз:",
            parse_mode="Markdown"
        )
        return TIME


async def add_reminder_repeat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle repeat option selection."""
    query = update.callback_query
    await query.answer()
    
    repeat_type = query.data.replace("repeat_", "")
    
    title = context.user_data.get("reminder_title")
    reminder_time = context.user_data.get("reminder_time")
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    
    # Save to database
    reminder_id = db.add_reminder(
        user_id=user_id,
        chat_id=chat_id,
        title=title,
        reminder_time=reminder_time,
        repeat_type=repeat_type
    )
    
    # Schedule the reminder
    bot = context.application.bot
    scheduler.schedule_reminder(bot, reminder_id, reminder_time)
    
    # Format confirmation message
    time_str = reminder_time.strftime("%d.%m.%Y о %H:%M")
    repeat_label = REPEAT_OPTIONS.get(repeat_type, repeat_type)
    
    await query.edit_message_text(
        f"✅ *Нагадування створено!*\n\n"
        f"📌 *Назва:* {title}\n"
        f"⏰ *Час:* {time_str}\n"
        f"🔄 *Повторення:* {repeat_label}",
        parse_mode="Markdown"
    )
    
    # Send menu
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Оберіть наступну дію:",
        reply_markup=menu.get_reminders_menu()
    )
    
    # Clear user data
    context.user_data.clear()
    
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the current conversation."""
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Дію скасовано.",
        parse_mode="Markdown",
        reply_markup=menu.get_main_menu()
    )
    return ConversationHandler.END


async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all active reminders for the user."""
    user_id = update.effective_user.id
    reminders = db.get_user_reminders(user_id)
    limits = db.get_user_limits(user_id)
    current_count = db.count_user_reminders(user_id)
    
    if not reminders:
        await update.message.reply_text(
            "📭 У вас немає активних нагадувань.\n\n"
            "Натисніть «➕ Нове нагадування» щоб створити!",
            reply_markup=menu.get_reminders_menu()
        )
        return
    
    message = f"📋 *Ваші нагадування* ({current_count}/{limits['reminders']}):\n\n"
    
    for reminder in reminders:
        reminder_id, title, reminder_time, repeat_type = reminder
        time = datetime.fromisoformat(reminder_time)
        time_str = time.strftime("%d.%m.%Y %H:%M")
        repeat_label = REPEAT_OPTIONS.get(repeat_type, repeat_type)
        
        message += f"🔹 *{title}*\n"
        message += f"   ⏰ {time_str}\n"
        message += f"   🔄 {repeat_label}\n\n"
    
    await update.message.reply_text(
        message, 
        parse_mode="Markdown",
        reply_markup=menu.get_reminders_menu()
    )


async def delete_reminder_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start delete reminder process."""
    user_id = update.effective_user.id
    reminders = db.get_user_reminders(user_id)
    
    if not reminders:
        await update.message.reply_text(
            "📭 У вас немає нагадувань для видалення."
        )
        return ConversationHandler.END
    
    # Create keyboard with reminders
    keyboard = []
    for reminder in reminders:
        reminder_id, title, _, _ = reminder
        # Truncate title if too long
        display_title = title[:30] + "..." if len(title) > 30 else title
        keyboard.append([
            InlineKeyboardButton(
                f"🗑 {display_title}",
                callback_data=f"delete_{reminder_id}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("❌ Скасувати", callback_data="delete_cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🗑 *Оберіть нагадування для видалення:*",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return 0


async def delete_reminder_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm and delete the reminder."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "delete_cancel":
        await query.edit_message_text("❌ Видалення скасовано.")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Оберіть дію:",
            reply_markup=menu.get_reminders_menu()
        )
        return ConversationHandler.END
    
    reminder_id = int(query.data.replace("delete_", ""))
    user_id = query.from_user.id
    
    # Get reminder info before deleting
    reminder = db.get_reminder_by_id(reminder_id)
    
    if reminder and db.delete_reminder(reminder_id, user_id):
        # Remove from scheduler
        scheduler.remove_scheduled_reminder(reminder_id)
        
        await query.edit_message_text(
            f"✅ Нагадування *{reminder[3]}* видалено!",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text("❌ Не вдалося видалити нагадування.")
    
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Оберіть дію:",
        reply_markup=menu.get_reminders_menu()
    )
    
    return ConversationHandler.END


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple health check handler for Render."""
    
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running!")
    
    def log_message(self, format, *args):
        pass  # Suppress logs


def run_health_server():
    """Run a simple HTTP server for health checks."""
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info(f"Health check server running on port {port}")
    server.serve_forever()


def main():
    """Start the bot."""
    token = os.getenv("BOT_TOKEN")
    
    if not token:
        logger.error("BOT_TOKEN not found in environment variables!")
        return
    
    # Initialize database
    db.init_db()
    
    # Post init function to start scheduler
    async def post_init(app):
        scheduler.start_scheduler()
        scheduler.load_all_reminders(app.bot)
        logger.info("Scheduler started!")
    
    # Create application
    application = Application.builder().token(token).post_init(post_init).build()
    
    # Add conversation handler for adding reminders
    add_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_reminder_start)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reminder_title)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reminder_time)],
            REPEAT: [CallbackQueryHandler(add_reminder_repeat, pattern="^repeat_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Add conversation handler for deleting reminders
    delete_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("delete", delete_reminder_start)],
        states={
            0: [CallbackQueryHandler(delete_reminder_confirm, pattern="^delete_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", list_reminders))
    application.add_handler(CommandHandler("clear", clear_chat))
    application.add_handler(CommandHandler("timezone", timezone_command))
    application.add_handler(add_conv_handler)
    application.add_handler(delete_conv_handler)
    
    # Mental health handlers
    application.add_handler(CommandHandler("mood", mh.mood_command))
    application.add_handler(CommandHandler("moodstats", mh.mood_stats_command))
    application.add_handler(CommandHandler("breathe", mh.breathe_command))
    application.add_handler(CommandHandler("cbt", mh.cbt_command))
    application.add_handler(CommandHandler("meds", mh.meds_command))
    
    # Mood callback handler
    application.add_handler(CallbackQueryHandler(
        mh.handle_mood_selection,
        pattern="^mood_"
    ))
    
    # Breathing callback handler
    application.add_handler(CallbackQueryHandler(
        mh.handle_breathing_selection,
        pattern="^breathe_"
    ))
    
    # CBT conversation handler
    cbt_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(mh.handle_cbt_selection, pattern="^cbt_")],
        states={
            mh.CBT_EXERCISE: [MessageHandler(filters.TEXT & ~filters.COMMAND, mh.handle_cbt_answer)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(cbt_conv_handler)
    
    # Medications conversation handler
    meds_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(mh.handle_meds_callback, pattern="^meds_")],
        states={
            mh.MED_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, mh.handle_med_name)],
            mh.MED_DOSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, mh.handle_med_dosage)],
            mh.MED_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, mh.handle_med_time)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(meds_conv_handler)
    
    # Medication taken/skip handler
    application.add_handler(CallbackQueryHandler(
        mh.handle_med_taken,
        pattern="^med_(taken|skip)_"
    ))
    
    # AI reminder callback handlers
    application.add_handler(CallbackQueryHandler(
        handle_ai_reminder_callback, 
        pattern="^ai_(confirm|cancel|edit_time|edit_repeat)$"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_ai_repeat_selection,
        pattern="^ai_repeat_"
    ))
    
    # Subscription handlers
    application.add_handler(CommandHandler("subscription", sub.subscription_command))
    application.add_handler(CallbackQueryHandler(
        sub.handle_subscription_callback,
        pattern="^sub_"
    ))
    application.add_handler(CallbackQueryHandler(
        sub.handle_payment_callback,
        pattern="^pay_"
    ))
    
    # Admin handlers
    application.add_handler(CommandHandler("admin", sub.admin_command))
    application.add_handler(CommandHandler("grant", sub.grant_premium_command))
    application.add_handler(CommandHandler("revoke", sub.revoke_premium_command))
    application.add_handler(CommandHandler("users", sub.users_command))
    application.add_handler(CommandHandler("broadcast", sub.broadcast_command))
    
    # Payment handlers
    from telegram.ext import PreCheckoutQueryHandler
    application.add_handler(PreCheckoutQueryHandler(sub.precheckout_callback))
    application.add_handler(MessageHandler(
        filters.SUCCESSFUL_PAYMENT,
        sub.successful_payment_callback
    ))
    
    # Handler for editing AI reminder time and menu buttons
    async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Route messages - check menu buttons, time edit, then chat."""
        text = update.message.text
        
        # Check for menu buttons first
        if text in menu.MENU_COMMANDS:
            handled = await handle_menu_button(update, context)
            if handled:
                return
            # If not handled, check if it's a command shortcut
            action = menu.MENU_COMMANDS.get(text, "")
            if action.startswith("/"):
                # Let it fall through to be handled by command handlers
                # We need to re-trigger command processing
                return
        
        # Check for AI reminder time edit
        handled = await handle_ai_time_edit(update, context)
        if not handled:
            await chat_with_gpt(update, context)
    
    # ChatGPT handler for regular messages (must be last)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        message_router
    ))
    
    # Start health check server in a separate thread
    health_thread = Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    # Run the bot
    logger.info("Bot started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
