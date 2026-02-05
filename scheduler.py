from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from telegram import Bot

import database as db

scheduler = AsyncIOScheduler()


def get_next_reminder_time(current_time: datetime, repeat_type: str) -> datetime:
    """Calculate the next reminder time based on repeat type."""
    if repeat_type == "daily":
        return current_time + timedelta(days=1)
    elif repeat_type == "weekly":
        return current_time + timedelta(weeks=1)
    elif repeat_type == "monthly":
        # Add approximately one month
        return current_time + timedelta(days=30)
    elif repeat_type == "hourly":
        return current_time + timedelta(hours=1)
    return None


async def send_reminder(bot: Bot, reminder_id: int):
    """Send a reminder notification to the user."""
    reminder = db.get_reminder_by_id(reminder_id)
    
    if not reminder:
        return
    
    _, user_id, chat_id, title, reminder_time, repeat_type = reminder
    
    # Send the reminder message
    message = f"🔔 *Нагадування!*\n\n📌 {title}"
    
    if repeat_type != "once":
        repeat_labels = {
            "hourly": "щогодини",
            "daily": "щодня",
            "weekly": "щотижня",
            "monthly": "щомісяця"
        }
        message += f"\n\n🔄 Повторення: {repeat_labels.get(repeat_type, repeat_type)}"
    
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error sending reminder {reminder_id}: {e}")
        return
    
    # Handle recurring reminders
    if repeat_type != "once":
        current_time = datetime.fromisoformat(reminder_time)
        next_time = get_next_reminder_time(current_time, repeat_type)
        
        if next_time:
            db.update_reminder_time(reminder_id, next_time)
            schedule_reminder(bot, reminder_id, next_time)
    else:
        # Deactivate one-time reminder
        db.delete_reminder(reminder_id, user_id)


def schedule_reminder(bot: Bot, reminder_id: int, reminder_time: datetime):
    """Schedule a reminder to be sent at the specified time."""
    job_id = f"reminder_{reminder_id}"
    
    # Remove existing job if it exists
    existing_job = scheduler.get_job(job_id)
    if existing_job:
        existing_job.remove()
    
    # Only schedule if the time is in the future
    if reminder_time > datetime.now():
        scheduler.add_job(
            send_reminder,
            trigger=DateTrigger(run_date=reminder_time),
            args=[bot, reminder_id],
            id=job_id,
            replace_existing=True
        )


def load_all_reminders(bot: Bot):
    """Load all active reminders from database and schedule them."""
    reminders = db.get_all_active_reminders()
    
    for reminder in reminders:
        reminder_id, _, _, _, reminder_time, _ = reminder
        time = datetime.fromisoformat(reminder_time)
        
        if time > datetime.now():
            schedule_reminder(bot, reminder_id, time)


def remove_scheduled_reminder(reminder_id: int):
    """Remove a scheduled reminder job."""
    job_id = f"reminder_{reminder_id}"
    existing_job = scheduler.get_job(job_id)
    if existing_job:
        existing_job.remove()


def start_scheduler():
    """Start the scheduler."""
    if not scheduler.running:
        scheduler.start()


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown()
