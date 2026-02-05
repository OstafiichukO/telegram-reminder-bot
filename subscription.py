"""Subscription management and admin features."""

import os
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import ContextTypes

import database as db
import menu

logger = logging.getLogger(__name__)

# Admin user IDs from environment
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# Subscription prices in Telegram Stars (XTR)
# Stars are whole numbers, ~$0.02-0.03 per star
SUBSCRIPTION_PRICES = {
    "monthly": {"stars": 50, "label": "⭐ Преміум (1 місяць)", "days": 30},
    "yearly": {"stars": 400, "label": "⭐ Преміум (1 рік)", "days": 365},
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
        
        monthly_price = SUBSCRIPTION_PRICES["monthly"]["stars"]
        yearly_price = SUBSCRIPTION_PRICES["yearly"]["stars"]
        
        message = f"""
📊 *Ваша підписка: Free*

*Використання:*
• Нагадувань: {reminders_count}/{limits['reminders']}
• Ліків: {meds_count}/{limits['medications']}
• Записів настрою/день: {limits['mood_per_day']}

⭐ *Переваги Premium:*
• ♾️ Безліміт усіх функцій
• 🚀 Пріоритетна підтримка
• 🎁 Нові функції першими

💫 *Ціни (Telegram Stars):*
• {monthly_price} ⭐ / місяць
• {yearly_price} ⭐ / рік (економія ~33%)
"""
        keyboard = [
            [InlineKeyboardButton("💫 Отримати Premium", callback_data="sub_buy")],
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
        monthly = SUBSCRIPTION_PRICES["monthly"]
        yearly = SUBSCRIPTION_PRICES["yearly"]
        
        keyboard = [
            [InlineKeyboardButton(
                f"📅 1 місяць — {monthly['stars']} ⭐", 
                callback_data="pay_monthly"
            )],
            [InlineKeyboardButton(
                f"📅 1 рік — {yearly['stars']} ⭐ (знижка ~33%)", 
                callback_data="pay_yearly"
            )],
            [InlineKeyboardButton("❌ Скасувати", callback_data="sub_cancel")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "💫 *Оберіть план підписки:*\n\n"
            "Оплата через Telegram Stars ⭐\n"
            "_Зірки можна придбати прямо в Telegram_",
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
    """Handle payment plan selection - send invoice with Telegram Stars."""
    query = update.callback_query
    await query.answer()
    
    plan = query.data.replace("pay_", "")
    
    # Get price info
    price_info = SUBSCRIPTION_PRICES.get(plan)
    if not price_info:
        await query.edit_message_text("❌ Невідомий план підписки.")
        return
    
    # Create invoice with Telegram Stars (XTR)
    # For digital goods, provider_token should be empty string
    prices = [LabeledPrice(label=price_info["label"], amount=price_info["stars"])]
    
    try:
        await query.edit_message_text(
            f"💫 Формую рахунок на {price_info['stars']} ⭐...",
            parse_mode="Markdown"
        )
        
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=price_info["label"],
            description=f"Преміум підписка на {price_info['days']} днів. Безліміт усіх функцій!",
            payload=f"premium_{plan}_{query.from_user.id}",
            provider_token="",  # Empty for digital goods with Stars
            currency="XTR",  # Telegram Stars
            prices=prices,
            start_parameter="premium-subscription",
        )
        
        logger.info(f"Invoice sent to user {query.from_user.id} for {plan} plan")
        
    except Exception as e:
        logger.error(f"Error sending invoice: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Помилка при створенні рахунку. Спробуйте пізніше.",
            reply_markup=menu.get_settings_menu()
        )


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle pre-checkout query.
    Must respond within 10 seconds or transaction is canceled.
    """
    query = update.pre_checkout_query
    
    try:
        # Parse payload to validate
        payload = query.invoice_payload
        parts = payload.split("_")
        
        if len(parts) != 3 or parts[0] != "premium":
            await query.answer(ok=False, error_message="Невірний формат замовлення.")
            return
        
        plan = parts[1]
        if plan not in SUBSCRIPTION_PRICES:
            await query.answer(ok=False, error_message="Невідомий план підписки.")
            return
        
        # All good - approve the payment
        await query.answer(ok=True)
        logger.info(f"Pre-checkout approved for user {query.from_user.id}, plan: {plan}")
        
    except Exception as e:
        logger.error(f"Pre-checkout error: {e}")
        await query.answer(ok=False, error_message="Помилка обробки замовлення. Спробуйте пізніше.")


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle successful payment.
    Store telegram_payment_charge_id for potential refunds.
    """
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    
    # Parse payload: premium_monthly_123456789
    parts = payload.split("_")
    plan = parts[1]
    user_id = int(parts[2])
    
    # Get payment charge ID for potential refunds
    telegram_charge_id = payment.telegram_payment_charge_id
    stars_paid = SUBSCRIPTION_PRICES[plan]["stars"]
    
    # Calculate expiration
    days = SUBSCRIPTION_PRICES[plan]["days"]
    expires = (datetime.now() + timedelta(days=days)).isoformat()
    
    # Update subscription in database
    db.set_subscription(user_id, "premium", expires)
    
    # Store payment info for potential refunds
    db.add_payment(
        user_id=user_id,
        telegram_charge_id=telegram_charge_id,
        plan=plan,
        stars_amount=stars_paid
    )
    
    logger.info(
        f"Payment successful! User: {user_id}, Plan: {plan}, "
        f"Stars: {stars_paid}, Charge ID: {telegram_charge_id}, Expires: {expires}"
    )
    
    await update.message.reply_text(
        f"🎉 *Дякуємо за оплату!*\n\n"
        f"💫 Ви оплатили: {stars_paid} ⭐\n"
        f"⭐ Ваша Premium підписка активована!\n"
        f"📅 Діє до: {datetime.fromisoformat(expires).strftime('%d.%m.%Y')}\n\n"
        f"Тепер ви маєте доступ до всіх функцій без обмежень! 🚀",
        parse_mode="Markdown",
        reply_markup=menu.get_main_menu()
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
/refund `user_id` `charge_id` - Повернути зірки
/users - Список користувачів
/broadcast `текст` - Розсилка всім

*Приклади:*
`/grant 123456789`
`/refund 123456789 abc123charge`
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


# ============ PAYMENT SUPPORT & TERMS ============

async def paysupport_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /paysupport command - required by Telegram for payment bots."""
    await update.message.reply_text(
        "💬 *Підтримка з питань оплати*\n\n"
        "Якщо у вас виникли проблеми з оплатою або підпискою:\n\n"
        "1️⃣ Перевірте статус підписки: /subscription\n"
        "2️⃣ Зв'яжіться з адміністратором бота\n"
        "3️⃣ Опишіть проблему детально\n\n"
        "📧 Ми відповімо якнайшвидше!\n\n"
        "_Зверніть увагу: підтримка Telegram не може допомогти "
        "з питаннями покупок через цього бота._",
        parse_mode="Markdown",
        reply_markup=menu.get_settings_menu()
    )


async def terms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /terms command - required by Telegram for payment bots."""
    await update.message.reply_text(
        "📜 *Умови використання*\n\n"
        "*1. Підписка Premium:*\n"
        "• Надає доступ до розширених функцій\n"
        "• Діє протягом оплаченого періоду\n"
        "• Автоматично не поновлюється\n\n"
        "*2. Оплата:*\n"
        "• Здійснюється через Telegram Stars\n"
        "• Після оплати підписка активується миттєво\n\n"
        "*3. Повернення коштів:*\n"
        "• Можливе протягом 24 годин після покупки\n"
        "• Зверніться через /paysupport\n\n"
        "*4. Відповідальність:*\n"
        "• Бот надає інформаційні послуги\n"
        "• Не замінює професійну медичну допомогу\n\n"
        "_Використовуючи бота, ви погоджуєтесь з цими умовами._",
        parse_mode="Markdown",
        reply_markup=menu.get_settings_menu()
    )


async def refund_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to refund a payment."""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас немає доступу.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text(
            "❌ Використання:\n"
            "`/refund user_id` - показати платежі\n"
            "`/refund user_id charge_id` - повернути кошти\n\n"
            "Charge ID можна знайти через `/refund user_id`",
            parse_mode="Markdown"
        )
        return
    
    try:
        target_user_id = int(context.args[0])
        
        # If only user_id provided, show their payments
        if len(context.args) == 1:
            payments = db.get_user_payments(target_user_id)
            
            if not payments:
                await update.message.reply_text(
                    f"📭 У користувача `{target_user_id}` немає платежів.",
                    parse_mode="Markdown"
                )
                return
            
            message = f"💳 *Платежі користувача* `{target_user_id}`:\n\n"
            for p_id, charge_id, plan, stars, status, created in payments:
                date = datetime.fromisoformat(created).strftime("%d.%m.%Y %H:%M")
                status_emoji = "✅" if status == "completed" else "↩️"
                message += f"{status_emoji} {plan}: {stars}⭐\n"
                message += f"   ID: `{charge_id[:20]}...`\n"
                message += f"   {date}\n\n"
            
            message += "Для повернення:\n`/refund user_id charge_id`"
            await update.message.reply_text(message, parse_mode="Markdown")
            return
        
        charge_id = context.args[1]
        
        # Check if payment exists
        payment = db.get_payment_by_charge_id(charge_id)
        if not payment:
            await update.message.reply_text(
                f"❌ Платіж з ID `{charge_id}` не знайдено.",
                parse_mode="Markdown"
            )
            return
        
        if payment[5] == "refunded":
            await update.message.reply_text("❌ Цей платіж вже було повернуто.")
            return
        
        # Refund using Telegram Bot API
        await context.bot.refund_star_payment(
            user_id=target_user_id,
            telegram_payment_charge_id=charge_id
        )
        
        # Update payment status
        db.update_payment_status(charge_id, "refunded")
        
        # Revoke premium
        db.set_subscription(target_user_id, "free", None)
        
        await update.message.reply_text(
            f"✅ *Повернення успішне!*\n\n"
            f"Користувач: `{target_user_id}`\n"
            f"Зірок повернуто: {payment[4]}⭐\n"
            f"Premium статус скасовано.",
            parse_mode="Markdown"
        )
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"💫 *Повернення коштів*\n\n"
                     f"Вам повернуто {payment[4]}⭐ за підписку.\n"
                     f"Ваш Premium статус деактивовано.",
                parse_mode="Markdown"
            )
        except:
            pass
            
    except Exception as e:
        logger.error(f"Refund error: {e}")
        await update.message.reply_text(
            f"❌ Помилка повернення: {e}",
            parse_mode="Markdown"
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
