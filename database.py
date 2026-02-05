import sqlite3
from datetime import datetime
from typing import Optional

DB_NAME = "reminders.db"


def init_db():
    """Initialize the database and create tables."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
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
    
    conn.commit()
    conn.close()


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
