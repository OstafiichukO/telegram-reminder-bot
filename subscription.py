"""Subscription management and admin features."""

import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import ContextTypes

import database as db
import menu

# Admin user IDs from environment
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# Subscription prices (in smallest currency unit, e.g., kopecks for UAH)
SUBSCRIPTION_PRICES = {
    "monthly": {"amount": 9900, "label": "Преміум (1 місяць)", "days": 30},
    "yearly": {"amount": 79900, "label": "Преміум (1 рік)", "days": 365},
}


def is_admin(user_id: int) -> bool:
    """Check if user is an admin."""
    return user_id in ADMIN_IDS


# ============ SUBSCRIPTION COMMANDS ============

async def subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show subscription status and options."""
    user_id = update.effective_user.id
    settings = db.get_or_create_user_settings(user_id)
    is_premium = db.is_premium(user_id)
    
    if is_premium:
        expires = settings.get("subscription_expires")
        if expires:
            exp_date = datetime.fromisoformat(expires).strftime("%d.%m.%Y")
            exp_text = f"до {exp_date}"
        else:
            exp_text = "безстроково ♾️"
        
        message = f"""
⭐ *Ваша підписка: Premium*

✅ Статус: Активна {exp_text}

*Ваші можливості:*
• Безліміт нагадувань
• Безліміт ліків
• Безліміт записів настрою
• Безліміт AI-повідомлень
• Пріоритетна підтримка

Дякуємо за підтримку! 💚
"""
        await update.message.reply_text(
            message, 
            parse_mode="Markdown",
            reply_markup=menu.get_settings_menu()
        )
    else:
        limits = db.SUBSCRIPTION_LIMITS["free"]
        
        # Get current usage
        reminders_count = db.count_user_reminders(user_id)
        meds_count = db.count_user_medications(user_id)
        
        message = f"""
📊 *Ваша підписка: Free*

*Використання:*
• Нагадувань: {reminders_count}/{limits['reminders']}
• Ліків: {meds_count}/{limits['medications']}
• AI-повідомлень/день: {limits['ai_messages_per_day']}

⭐ *Переваги Premium:*
• ♾️ Безліміт усіх функцій
• 🚀 Пріоритетна підтримка
• 🎁 Нові функції першими

💰 *Ціни:*
• 99 грн/місяць
• 799 грн/рік (економія 33%)
"""
        keyboard = [
            [InlineKeyboardButton("⭐ Отримати Premium", callback_data="sub_buy")],
            [InlineKeyboardButton("🔙 Назад", callback_data="sub_back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message, 
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )


async def handle_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle subscription button callbacks."""
    query = update.callback_query
    await query.answer()
    
    action = query.data.replace("sub_", "")
    
    if action == "buy":
        keyboard = [
            [InlineKeyboardButton(
                "📅 1 місяць — 99 грн", 
                callback_data="pay_monthly"
            )],
            [InlineKeyboardButton(
                "📅 1 рік — 799 грн (знижка 33%)", 
                callback_data="pay_yearly"
            )],
            [InlineKeyboardButton("❌ Скасувати", callback_data="sub_cancel")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "⭐ *Оберіть план підписки:*\n\n"
            "Оплата через Telegram Payments (карта Visa/Mastercard)",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    
    elif action == "cancel" or action == "back":
        await query.edit_message_text("Оберіть опцію:")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="⚙️ Налаштування",
            reply_markup=menu.get_settings_menu()
        )


async def handle_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment plan selection."""
    query = update.callback_query
    await query.answer()
    
    plan = query.data.replace("pay_", "")
    
    payment_token = os.getenv("PAYMENT_PROVIDER_TOKEN")
    
    if not payment_token:
        # No payment provider - show manual payment info
        await query.edit_message_text(
            "💳 *Оплата підписки*\n\n"
            "Для оплати зв'яжіться з адміністратором:\n"
            "@YourAdminUsername\n\n"
            "Або надішліть оплату на:\n"
            "• Monobank: 1234 5678 9012 3456\n"
            "• PayPal: your@email.com\n\n"
            "Після оплати надішліть скріншот адміністратору.",
            parse_mode="Markdown"
        )
        return
    
    # Send invoice via Telegram Payments
    price_info = SUBSCRIPTION_PRICES.get(plan)
    if not price_info:
        return
    
    prices = [LabeledPrice(label=price_info["label"], amount=price_info["amount"])]
    
    await context.bot.send_invoice(
        chat_id=query.message.chat_id,
        title=price_info["label"],
        description="Преміум підписка на бота для ментального здоров'я",
        payload=f"premium_{plan}_{query.from_user.id}",
        provider_token=payment_token,
        currency="UAH",
        prices=prices,
        start_parameter="premium-subscription",
    )


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pre-checkout query."""
    query = update.pre_checkout_query
    await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle successful payment."""
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    
    # Parse payload: premium_monthly_123456789
    parts = payload.split("_")
    plan = parts[1]
    user_id = int(parts[2])
    
    # Calculate expiration
    days = SUBSCRIPTION_PRICES[plan]["days"]
    expires = (datetime.now() + timedelta(days=days)).isoformat()
    
    # Update subscription
    db.set_subscription(user_id, "premium", expires)
    
    await update.message.reply_text(
        "🎉 *Дякуємо за оплату!*\n\n"
        "⭐ Ваша Premium підписка активована!\n\n"
        "Тепер ви маєте доступ до всіх функцій без обмежень.",
        parse_mode="Markdown"
    )


# ============ ADMIN COMMANDS ============

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin panel."""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас немає доступу до адмін-панелі.")
        return
    
    # Get stats
    all_users = db.get_all_users()
    premium_users = db.get_premium_users()
    
    message = f"""
👑 *Адмін-панель*

📊 *Статистика:*
• Всього користувачів: {len(all_users)}
• Premium користувачів: {len(premium_users)}

*Команди:*
/grant `user_id` - Надати безлімітний Premium
/revoke `user_id` - Забрати Premium
/users - Список користувачів
/broadcast `текст` - Розсилка всім

*Приклад:*
`/grant 123456789`
"""
    await update.message.reply_text(message, parse_mode="Markdown")


async def grant_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Grant unlimited premium to a user."""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас немає доступу.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "❌ Вкажіть user_id:\n`/grant 123456789`",
            parse_mode="Markdown"
        )
        return
    
    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Невірний user_id")
        return
    
    # Grant unlimited premium (no expiration)
    db.set_subscription(target_user_id, "premium", None)
    
    await update.message.reply_text(
        f"✅ Користувачу `{target_user_id}` надано безлімітний Premium!",
        parse_mode="Markdown"
    )
    
    # Notify user if possible
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text="🎁 *Вітаємо!*\n\nВам надано безкоштовну Premium підписку! ⭐\n\nКористуйтесь усіма функціями без обмежень.",
            parse_mode="Markdown"
        )
    except:
        pass


async def revoke_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Revoke premium from a user."""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас немає доступу.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "❌ Вкажіть user_id:\n`/revoke 123456789`",
            parse_mode="Markdown"
        )
        return
    
    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Невірний user_id")
        return
    
    # Revoke premium
    db.set_subscription(target_user_id, "free", None)
    
    await update.message.reply_text(
        f"✅ У користувача `{target_user_id}` забрано Premium.",
        parse_mode="Markdown"
    )


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all users."""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас немає доступу.")
        return
    
    users = db.get_all_users()
    
    if not users:
        await update.message.reply_text("📭 Немає користувачів.")
        return
    
    message = "👥 *Користувачі:*\n\n"
    
    for i, (uid, tz, lang, sub_type, sub_exp) in enumerate(users[:50]):  # Limit to 50
        status = "⭐" if sub_type == "premium" else "👤"
        message += f"{status} `{uid}` — {sub_type}\n"
    
    if len(users) > 50:
        message += f"\n_...та ще {len(users) - 50} користувачів_"
    
    await update.message.reply_text(message, parse_mode="Markdown")


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast message to all users."""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас немає доступу.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "❌ Вкажіть текст:\n`/broadcast Привіт всім!`",
            parse_mode="Markdown"
        )
        return
    
    text = " ".join(context.args)
    users = db.get_all_users()
    
    sent = 0
    failed = 0
    
    status_msg = await update.message.reply_text("📤 Розсилка розпочата...")
    
    for uid, _, _, _, _ in users:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"📢 *Оголошення:*\n\n{text}",
                parse_mode="Markdown"
            )
            sent += 1
        except:
            failed += 1
    
    await status_msg.edit_text(
        f"✅ Розсилка завершена!\n\n"
        f"📬 Доставлено: {sent}\n"
        f"❌ Не доставлено: {failed}"
    )


# ============ LIMIT CHECKING ============

def check_limit(user_id: int, limit_type: str, current_count: int = None) -> tuple[bool, str]:
    """
    Check if user is within their subscription limits.
    Returns (is_allowed, message).
    """
    limits = db.get_user_limits(user_id)
    limit_value = limits.get(limit_type, 0)
    
    if current_count is None:
        # Get current count based on type
        if limit_type == "reminders":
            current_count = db.count_user_reminders(user_id)
        elif limit_type == "medications":
            current_count = db.count_user_medications(user_id)
        elif limit_type == "mood_per_day":
            current_count = db.count_today_mood_entries(user_id)
        else:
            current_count = 0
    
    if current_count >= limit_value:
        return False, (
            f"⚠️ *Досягнуто ліміт!*\n\n"
            f"На безкоштовному плані доступно: {limit_value}\n"
            f"Ви використали: {current_count}\n\n"
            f"⭐ Оновіть до Premium для безлімітного доступу!\n"
            f"Використайте /subscription"
        )
    
    return True, ""
