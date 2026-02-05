import os
import logging
from datetime import datetime
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
    
    gpt_status = "✅ Увімкнено" if openai_client else "❌ Не налаштовано"
    
    welcome_text = f"""
👋 Привіт, {user.first_name}!

Я бот для нагадувань з підтримкою ChatGPT. Ось що я вмію:

📝 /add - Створити нове нагадування
📋 /list - Переглянути всі нагадування
🗑 /delete - Видалити нагадування
🧹 /clear - Очистити історію чату з AI
❓ /help - Допомога

🤖 *ChatGPT:* {gpt_status}
Просто напишіть повідомлення, і я відповім!

Почнімо? Використай /add щоб створити нагадування або просто напиши мені!
"""
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message."""
    help_text = """
📚 *Довідка по командах:*

/add - Створити нове нагадування
  1️⃣ Введіть назву нагадування
  2️⃣ Вкажіть час (формат: ДД.ММ.РРРР ГГ:ХХ)
  3️⃣ Оберіть частоту повторення

/list - Показати всі активні нагадування

/delete - Видалити нагадування

/clear - Очистити історію чату з AI

/cancel - Скасувати поточну дію

*Формат часу:*
`25.12.2025 14:30` - конкретна дата і час
`14:30` - сьогодні о вказаний час

*Типи повторення:*
• Один раз - нагадування спрацює лише раз
• Щогодини - кожну годину
• Щодня - кожен день
• Щотижня - кожен тиждень
• Щомісяця - кожен місяць

🤖 *ChatGPT:*
Просто напишіть повідомлення (не команду), і я відповім за допомогою AI!
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def clear_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear chat history with AI."""
    user_id = update.effective_user.id
    if user_id in chat_history:
        chat_history[user_id] = []
    await update.message.reply_text("🗑 Історію чату очищено!")


async def chat_with_gpt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular messages with ChatGPT."""
    if not openai_client:
        await update.message.reply_text(
            "⚠️ ChatGPT не налаштовано. Додайте OPENAI_API_KEY."
        )
        return
    
    user_id = update.effective_user.id
    user_message = update.message.text
    
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
    
    try:
        # Call ChatGPT
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Ти корисний асистент. Відповідай українською мовою, якщо користувач пише українською. Будь дружнім і корисним."
                },
                *chat_history[user_id]
            ],
            max_tokens=1000
        )
        
        assistant_message = response.choices[0].message.content
        
        # Add assistant response to history
        chat_history[user_id].append({
            "role": "assistant",
            "content": assistant_message
        })
        
        await update.message.reply_text(assistant_message)
        
    except Exception as e:
        logger.error(f"ChatGPT error: {e}")
        await update.message.reply_text(
            "❌ Помилка при зверненні до ChatGPT. Спробуйте пізніше."
        )


async def add_reminder_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the add reminder conversation."""
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
    
    # Clear user data
    context.user_data.clear()
    
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the current conversation."""
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Дію скасовано.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all active reminders for the user."""
    user_id = update.effective_user.id
    reminders = db.get_user_reminders(user_id)
    
    if not reminders:
        await update.message.reply_text(
            "📭 У вас немає активних нагадувань.\n\n"
            "Використайте /add щоб створити нове!"
        )
        return
    
    message = "📋 *Ваші нагадування:*\n\n"
    
    for reminder in reminders:
        reminder_id, title, reminder_time, repeat_type = reminder
        time = datetime.fromisoformat(reminder_time)
        time_str = time.strftime("%d.%m.%Y %H:%M")
        repeat_label = REPEAT_OPTIONS.get(repeat_type, repeat_type)
        
        message += f"🔹 *{title}*\n"
        message += f"   ⏰ {time_str}\n"
        message += f"   🔄 {repeat_label}\n"
        message += f"   🆔 ID: `{reminder_id}`\n\n"
    
    message += "Для видалення використайте /delete"
    
    await update.message.reply_text(message, parse_mode="Markdown")


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
    application.add_handler(add_conv_handler)
    application.add_handler(delete_conv_handler)
    
    # ChatGPT handler for regular messages (must be last)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        chat_with_gpt
    ))
    
    # Start health check server in a separate thread
    health_thread = Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    # Run the bot
    logger.info("Bot started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
