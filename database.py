import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List

DB_NAME = "reminders.db"


def init_db():
    """Initialize the database and create tables."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Reminders table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            reminder_time TEXT NOT NULL,
            repeat_type TEXT DEFAULT 'once',
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Mood entries table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mood_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mood_score INTEGER NOT NULL,
            mood_emoji TEXT,
            note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Medications table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            dosage TEXT,
            schedule_time TEXT NOT NULL,
            repeat_type TEXT DEFAULT 'daily',
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Medication logs (taken/skipped)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medication_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medication_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            logged_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (medication_id) REFERENCES medications(id)
        )
    """)
    
    # User settings (timezone, language, subscription)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            timezone TEXT DEFAULT 'Europe/Kyiv',
            language TEXT DEFAULT 'uk',
            subscription_type TEXT DEFAULT 'free',
            subscription_expires TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()


# ============ MOOD TRACKING ============

def add_mood_entry(user_id: int, mood_score: int, mood_emoji: str, note: str = None) -> int:
    """Add a mood entry."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO mood_entries (user_id, mood_score, mood_emoji, note)
        VALUES (?, ?, ?, ?)
    """, (user_id, mood_score, mood_emoji, note))
    
    entry_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return entry_id


def get_mood_history(user_id: int, days: int = 7) -> List[tuple]:
    """Get mood history for the past N days."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    since = (datetime.now() - timedelta(days=days)).isoformat()
    
    cursor.execute("""
        SELECT mood_score, mood_emoji, note, created_at
        FROM mood_entries
        WHERE user_id = ? AND created_at >= ?
        ORDER BY created_at DESC
    """, (user_id, since))
    
    entries = cursor.fetchall()
    conn.close()
    
    return entries


def get_mood_stats(user_id: int, days: int = 30) -> dict:
    """Get mood statistics for a user."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    since = (datetime.now() - timedelta(days=days)).isoformat()
    
    cursor.execute("""
        SELECT AVG(mood_score), MIN(mood_score), MAX(mood_score), COUNT(*)
        FROM mood_entries
        WHERE user_id = ? AND created_at >= ?
    """, (user_id, since))
    
    result = cursor.fetchone()
    conn.close()
    
    return {
        "average": round(result[0], 1) if result[0] else 0,
        "min": result[1] or 0,
        "max": result[2] or 0,
        "count": result[3] or 0
    }


# ============ MEDICATIONS ============

def add_medication(user_id: int, chat_id: int, name: str, dosage: str, 
                   schedule_time: str, repeat_type: str = "daily") -> int:
    """Add a medication reminder."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO medications (user_id, chat_id, name, dosage, schedule_time, repeat_type)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, chat_id, name, dosage, schedule_time, repeat_type))
    
    med_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return med_id


def get_user_medications(user_id: int) -> List[tuple]:
    """Get all active medications for a user."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, name, dosage, schedule_time, repeat_type
        FROM medications
        WHERE user_id = ? AND is_active = 1
        ORDER BY schedule_time
    """, (user_id,))
    
    meds = cursor.fetchall()
    conn.close()
    
    return meds


def get_all_active_medications() -> List[tuple]:
    """Get all active medications from all users."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, user_id, chat_id, name, dosage, schedule_time, repeat_type
        FROM medications
        WHERE is_active = 1
    """)
    
    meds = cursor.fetchall()
    conn.close()
    
    return meds


def get_medication_by_id(med_id: int) -> Optional[tuple]:
    """Get a medication by ID."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, user_id, chat_id, name, dosage, schedule_time, repeat_type
        FROM medications
        WHERE id = ?
    """, (med_id,))
    
    med = cursor.fetchone()
    conn.close()
    
    return med


def delete_medication(med_id: int, user_id: int) -> bool:
    """Delete a medication."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE medications
        SET is_active = 0
        WHERE id = ? AND user_id = ?
    """, (med_id, user_id))
    
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    
    return affected > 0


def log_medication_taken(med_id: int, user_id: int, status: str = "taken"):
    """Log that medication was taken or skipped."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO medication_logs (medication_id, user_id, status)
        VALUES (?, ?, ?)
    """, (med_id, user_id, status))
    
    conn.commit()
    conn.close()


def get_medication_adherence(user_id: int, days: int = 7) -> dict:
    """Get medication adherence stats."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    since = (datetime.now() - timedelta(days=days)).isoformat()
    
    cursor.execute("""
        SELECT status, COUNT(*)
        FROM medication_logs
        WHERE user_id = ? AND logged_at >= ?
        GROUP BY status
    """, (user_id, since))
    
    results = cursor.fetchall()
    conn.close()
    
    stats = {"taken": 0, "skipped": 0, "missed": 0}
    for status, count in results:
        stats[status] = count
    
    total = sum(stats.values())
    stats["adherence_rate"] = round(stats["taken"] / total * 100, 1) if total > 0 else 0
    
    return stats


# ============ USER SETTINGS ============

def get_or_create_user_settings(user_id: int) -> dict:
    """Get or create user settings."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT timezone, language, subscription_type, subscription_expires
        FROM user_settings
        WHERE user_id = ?
    """, (user_id,))
    
    result = cursor.fetchone()
    
    if not result:
        cursor.execute("""
            INSERT INTO user_settings (user_id)
            VALUES (?)
        """, (user_id,))
        conn.commit()
        result = ('Europe/Kyiv', 'uk', 'free', None)
    
    conn.close()
    
    return {
        "timezone": result[0],
        "language": result[1],
        "subscription_type": result[2],
        "subscription_expires": result[3]
    }


def add_reminder(
    user_id: int,
    chat_id: int,
    title: str,
    reminder_time: datetime,
    repeat_type: str = "once"
) -> int:
    """Add a new reminder and return its ID."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO reminders (user_id, chat_id, title, reminder_time, repeat_type)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, chat_id, title, reminder_time.isoformat(), repeat_type))
    
    reminder_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return reminder_id


def get_user_reminders(user_id: int) -> list:
    """Get all active reminders for a user."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, title, reminder_time, repeat_type
        FROM reminders
        WHERE user_id = ? AND is_active = 1
        ORDER BY reminder_time
    """, (user_id,))
    
    reminders = cursor.fetchall()
    conn.close()
    
    return reminders


def get_all_active_reminders() -> list:
    """Get all active reminders from all users."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, user_id, chat_id, title, reminder_time, repeat_type
        FROM reminders
        WHERE is_active = 1
    """)
    
    reminders = cursor.fetchall()
    conn.close()
    
    return reminders


def get_reminder_by_id(reminder_id: int) -> Optional[tuple]:
    """Get a specific reminder by ID."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, user_id, chat_id, title, reminder_time, repeat_type
        FROM reminders
        WHERE id = ?
    """, (reminder_id,))
    
    reminder = cursor.fetchone()
    conn.close()
    
    return reminder


def delete_reminder(reminder_id: int, user_id: int) -> bool:
    """Delete a reminder (soft delete by setting is_active = 0)."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE reminders
        SET is_active = 0
        WHERE id = ? AND user_id = ?
    """, (reminder_id, user_id))
    
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    
    return affected > 0


def update_reminder_time(reminder_id: int, new_time: datetime):
    """Update reminder time (used for recurring reminders)."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE reminders
        SET reminder_time = ?
        WHERE id = ?
    """, (new_time.isoformat(), reminder_id))
    
    conn.commit()
    conn.close()
