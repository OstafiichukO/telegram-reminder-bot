import os
import logging
from datetime import datetime, timedelta
from threading import Thread
from dotenv import load_dotenv
from http.server import HTTPServer, BaseHTTPRequestHandler

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

# External ChatGPT bot
CHATGPT_BOT = "@chatgpt_gidbot"
CHATGPT_BOT_ESCAPED = "@chatgpt\\_gidbot"  # Escaped for Markdown

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
    
    sub_status = "⭐ Premium" if is_premium else "Free"
    
    welcome_text = f"""
👋 Привіт, {user.first_name}!

Я ваш персональний асистент для ментального здоров'я та продуктивності.

📊 Ваш план: *{sub_status}*

*Використовуйте меню нижче* для швидкого доступу до функцій!

🤖 Для AI-чату використовуйте {CHATGPT_BOT_ESCAPED}
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
        keyboard = [[InlineKeyboardButton(f"🤖 Відкрити {CHATGPT_BOT}", url=f"https://t.me/chatgpt_gidbot")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🤖 *AI Чат*\n\n"
            f"Для спілкування з ChatGPT використовуйте бота:\n"
            f"{CHATGPT_BOT_ESCAPED}\n\n"
            f"Він допоможе вам з будь-якими питаннями!",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        return True
    
    # These are handled by ConversationHandlers - don't handle here
    elif action in ["/add", "/delete"]:
        return False  # Let ConversationHandler handle these
    
    # Handle simple commands directly
    elif action == "/list":
        await list_reminders(update, context)
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
Для чату з AI використовуйте {CHATGPT_BOT_ESCAPED}

*⏰ Формат часу:*
`25.12.2025 14:30` або `14:30`

*🔄 Повторення:*
Один раз • Щогодини • Щодня • Щотижня • Щомісяця

*💡 Поради:*
• Записуйте настрій щодня для кращого розуміння себе
• Використовуйте дихальні вправи при стресі
"""
    await update.message.reply_text(
        help_text, 
        parse_mode="Markdown",
        reply_markup=menu.get_main_menu()
    )


async def handle_unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unknown text messages."""
    keyboard = [[InlineKeyboardButton(f"🤖 Відкрити {CHATGPT_BOT}", url="https://t.me/chatgpt_gidbot")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🤔 Я не розумію це повідомлення.\n\n"
        f"Використовуйте меню нижче для навігації або {CHATGPT_BOT} для AI-чату.",
        reply_markup=reply_markup
    )


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
        entry_points=[
            CommandHandler("add", add_reminder_start),
            MessageHandler(filters.Regex("^➕ Нове нагадування$"), add_reminder_start),
        ],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^🔙"), add_reminder_title)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^🔙"), add_reminder_time)],
            REPEAT: [CallbackQueryHandler(add_reminder_repeat, pattern="^repeat_")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^🔙 Головне меню$"), cancel),
        ],
    )
    
    # Add conversation handler for deleting reminders
    delete_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("delete", delete_reminder_start),
            MessageHandler(filters.Regex("^🗑 Видалити$"), delete_reminder_start),
        ],
        states={
            0: [CallbackQueryHandler(delete_reminder_confirm, pattern="^delete_")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^🔙 Головне меню$"), cancel),
        ],
    )
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", list_reminders))
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
            mh.CBT_EXERCISE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^🔙"), mh.handle_cbt_answer)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^🔙 Головне меню$"), cancel),
        ],
    )
    application.add_handler(cbt_conv_handler)
    
    # Medications conversation handler
    meds_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(mh.handle_meds_callback, pattern="^meds_")],
        states={
            mh.MED_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^🔙"), mh.handle_med_name)],
            mh.MED_DOSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^🔙"), mh.handle_med_dosage)],
            mh.MED_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^🔙"), mh.handle_med_time)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^🔙 Головне меню$"), cancel),
        ],
    )
    application.add_handler(meds_conv_handler)
    
    # Medication taken/skip handler
    application.add_handler(CallbackQueryHandler(
        mh.handle_med_taken,
        pattern="^med_(taken|skip)_"
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
    
    # Handler for menu buttons and unknown messages
    async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Route messages - check menu buttons first."""
        text = update.message.text
        
        # Check for menu buttons
        if text in menu.MENU_COMMANDS:
            handled = await handle_menu_button(update, context)
            if handled:
                return
        
        # Unknown message - show help
        await handle_unknown_message(update, context)
    
    # Message handler (must be last)
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
