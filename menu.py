"""Persistent menu (Reply Keyboard) for easy navigation."""

from telegram import ReplyKeyboardMarkup, KeyboardButton

# Main menu keyboard
def get_main_menu():
    """Get the main menu keyboard."""
    keyboard = [
        [KeyboardButton("📝 Нагадування"), KeyboardButton("💚 Здоров'я")],
        [KeyboardButton("🤖 AI Чат"), KeyboardButton("⚙️ Налаштування")],
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True
    )


# Reminders submenu
def get_reminders_menu():
    """Get reminders submenu."""
    keyboard = [
        [KeyboardButton("➕ Нове нагадування"), KeyboardButton("📋 Мої нагадування")],
        [KeyboardButton("🗑 Видалити"), KeyboardButton("🔙 Головне меню")],
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True
    )


# Health submenu
def get_health_menu():
    """Get health submenu."""
    keyboard = [
        [KeyboardButton("🎭 Настрій"), KeyboardButton("📊 Статистика")],
        [KeyboardButton("🫁 Дихання"), KeyboardButton("🧠 CBT вправи")],
        [KeyboardButton("💊 Ліки"), KeyboardButton("🔙 Головне меню")],
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True
    )


# Settings submenu
def get_settings_menu():
    """Get settings submenu."""
    keyboard = [
        [KeyboardButton("⭐ Підписка"), KeyboardButton("🌍 Часовий пояс")],
        [KeyboardButton("❓ Допомога"), KeyboardButton("🔙 Головне меню")],
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True
    )


# Menu button text to command mapping
MENU_COMMANDS = {
    # Main menu
    "📝 Нагадування": "menu_reminders",
    "💚 Здоров'я": "menu_health",
    "🤖 AI Чат": "menu_ai",
    "⚙️ Налаштування": "menu_settings",
    
    # Reminders submenu
    "➕ Нове нагадування": "/add",
    "📋 Мої нагадування": "/list",
    "🗑 Видалити": "/delete",
    
    # Health submenu
    "🎭 Настрій": "/mood",
    "📊 Статистика": "/moodstats",
    "🫁 Дихання": "/breathe",
    "🧠 CBT вправи": "/cbt",
    "💊 Ліки": "/meds",
    
    # Settings submenu
    "⭐ Підписка": "/subscription",
    "🌍 Часовий пояс": "/timezone",
    "❓ Допомога": "/help",
    
    # Back button
    "🔙 Головне меню": "menu_main",
}
