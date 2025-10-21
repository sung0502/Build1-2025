# core/timeparse.py
"""
Time parsing utilities for TimeBuddy.
Extracts dates, times, and durations from natural language.
"""
import re
from datetime import datetime, date, timedelta
from typing import Optional, Tuple
import dateparser


def parse_time_of_day(text: str) -> Optional[str]:
    """
    Parse time from text, return in HH:MM format.
    
    Examples:
        "3pm" -> "15:00"
        "9:30am" -> "09:30"
        "14:30" -> "14:30"
    """
    text = text.strip().upper()
    
    # Try HH:MM AM/PM
    match = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM)', text)
    if match:
        h, m, ampm = match.groups()
        h = int(h)
        if ampm == 'PM' and h != 12:
            h += 12
        elif ampm == 'AM' and h == 12:
            h = 0
        return f"{h:02d}:{m}"
    
    # Try H AM/PM (no minutes)
    match = re.search(r'(\d{1,2})\s*(AM|PM)', text)
    if match:
        h, ampm = match.groups()
        h = int(h)
        if ampm == 'PM' and h != 12:
            h += 12
        elif ampm == 'AM' and h == 12:
            h = 0
        return f"{h:02d}:00"
    
    # Try 24-hour format HH:MM
    match = re.search(r'(\d{1,2}):(\d{2})', text)
    if match:
        h, m = match.groups()
        h = int(h)
        m = int(m)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    
    # Try single number (assume 24-hour)
    match = re.search(r'\b(\d{1,2})\b', text)
    if match:
        h = int(match.group(1))
        if 0 <= h <= 23:
            return f"{h:02d}:00"
    
    return None


def infer_date(text: str, today_dt: date) -> str:
    """
    Infer date from text, return in YYYY-MM-DD format.
    
    Examples:
        "tomorrow" -> tomorrow's date
        "next monday" -> next Monday's date
        "jan 15" -> January 15 of current/next year
    """
    text_lower = text.lower()
    
    # Today
    if 'today' in text_lower:
        return today_dt.isoformat()
    
    # Tomorrow
    if 'tomorrow' in text_lower:
        return (today_dt + timedelta(days=1)).isoformat()
    
    # Day names
    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    for i, day_name in enumerate(days):
        if day_name in text_lower:
            days_ahead = i - today_dt.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return (today_dt + timedelta(days=days_ahead)).isoformat()
    
    # Try dateparser for complex dates
    try:
        parsed = dateparser.parse(
            text,
            settings={
                'PREFER_DATES_FROM': 'future',
                'RELATIVE_BASE': datetime.combine(today_dt, datetime.min.time())
            }
        )
        if parsed:
            return parsed.date().isoformat()
    except:
        pass
    
    # Default to today
    return today_dt.isoformat()


def parse_duration_minutes(text: str) -> Optional[int]:
    """
    Parse duration from text, return in minutes.
    
    Examples:
        "2 hours" -> 120
        "30 min" -> 30
        "1.5 hours" -> 90
    """
    # Hours
    match = re.search(r'(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b', text, re.IGNORECASE)
    if match:
        hours = float(match.group(1))
        return int(hours * 60)
    
    # Minutes
    match = re.search(r'(\d+)\s*(?:minutes?|mins?|m)\b', text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    
    return None


def quick_task_title_guess(text: str) -> str:
    """
    Extract likely task title from user text.

    Examples:
        "add team meeting tomorrow" -> "Team Meeting"
        "schedule workout at 7am" -> "Workout"
        "add workout tomorrow at 7am for 45 minutes" -> "Workout"
    """
    text = text.lower()

    # Remove common trigger words
    for trigger in ['add', 'schedule', 'create', 'plan', 'book', 'set up', 'set', 'remind me to', 'reminder']:
        text = text.replace(trigger, '')

    # Remove complete time expressions with "at" (do this before removing individual parts)
    # "at 7am", "at 7:30pm", "at 14:00", etc.
    text = re.sub(r'\bat\s+\d{1,2}:\d{2}\s*(?:am|pm)?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\bat\s+\d{1,2}\s*(?:am|pm)?', '', text, flags=re.IGNORECASE)  # Made am/pm optional
    text = re.sub(r'\bat\s+\d{1,2}(?:\s|$)', ' ', text)  # "at 7 " or "at 7" at end

    # Remove duration expressions with "for" (do this before removing standalone durations)
    text = re.sub(r'\bfor\s+\d+(?:\.\d+)?\s*(?:hours?|hrs?|h)\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\bfor\s+\d+\s*(?:minutes?|mins?|m)\b', '', text, flags=re.IGNORECASE)

    # Remove standalone time expressions (any leftover time patterns)
    text = re.sub(r'\b\d{1,2}:\d{2}\s*(?:am|pm)?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d{1,2}\s*(?:am|pm)\b', '', text, flags=re.IGNORECASE)

    # Remove standalone duration expressions
    text = re.sub(r'\b\d+(?:\.\d+)?\s*(?:hours?|hrs?|h)\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d+\s*(?:minutes?|mins?|m)\b', '', text, flags=re.IGNORECASE)

    # Remove any leftover am/pm markers
    text = re.sub(r'\b(?:am|pm)\b', '', text, flags=re.IGNORECASE)

    # Remove date expressions
    for word in ['tomorrow', 'today', 'tonight', 'morning', 'afternoon', 'evening', 'next week', 'next monday', 'next tuesday', 'next wednesday', 'next thursday', 'next friday', 'next saturday', 'next sunday']:
        text = text.replace(word, '')

    # Remove day names
    for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']:
        text = re.sub(r'\b' + day + r'\b', '', text, flags=re.IGNORECASE)

    # Remove leftover connector words and prepositions
    for connector in [' for ', ' at ', ' on ', ' from ', ' to ', ' by ', ' in ', ' the ']:
        text = text.replace(connector, ' ')

    # Remove any leftover standalone numbers
    text = re.sub(r'\b\d+\b', '', text)

    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    if not text:
        return "New Task"

    # Capitalize first letter of each word
    return ' '.join(word.capitalize() for word in text.split())


def parse_create_minimum(text: str, today_dt: date) -> Tuple[str, str, str, int]:
    """
    Parse minimum required fields for task creation.
    
    Returns:
        (title, date, start_time, duration)
    """
    title = quick_task_title_guess(text)
    date_str = infer_date(text, today_dt)
    start_time = parse_time_of_day(text) or "09:00"
    duration = parse_duration_minutes(text) or 60
    
    return title, date_str, start_time, duration
