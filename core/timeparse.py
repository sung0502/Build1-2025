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
        "Oct 29" -> October 29 of current/next year
        "10/29" -> October 29
    """
    text_lower = text.lower()

    # Today
    if 'today' in text_lower:
        return today_dt.isoformat()

    # Tomorrow
    if 'tomorrow' in text_lower:
        return (today_dt + timedelta(days=1)).isoformat()

    # Try explicit date patterns first (before dateparser)
    # Format: "Oct 29", "October 29", "jan 15", etc.
    month_pattern = r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?\b'
    match = re.search(month_pattern, text_lower, re.IGNORECASE)
    if match:
        month_abbr = match.group(1)[:3].lower()
        day = int(match.group(2))

        month_map = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
        }

        month_num = month_map.get(month_abbr)
        if month_num:
            # Determine year (current year or next year)
            year = today_dt.year
            try:
                candidate_date = date(year, month_num, day)
                # If date is in the past, try next year
                if candidate_date < today_dt:
                    candidate_date = date(year + 1, month_num, day)
                return candidate_date.isoformat()
            except ValueError:
                # Invalid date, fall through to dateparser
                pass

    # Format: "10/29", "10/29/25", "10/29/2025"
    slash_pattern = r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b'
    match = re.search(slash_pattern, text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year_str = match.group(3)

        if year_str:
            year = int(year_str)
            if year < 100:  # 2-digit year
                year += 2000
        else:
            # No year specified, use current or next year
            year = today_dt.year
            try:
                candidate_date = date(year, month, day)
                if candidate_date < today_dt:
                    year += 1
            except ValueError:
                pass

        try:
            return date(year, month, day).isoformat()
        except ValueError:
            # Invalid date, fall through
            pass

    # Day names (next occurrence)
    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    for i, day_name in enumerate(days):
        if day_name in text_lower:
            days_ahead = i - today_dt.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return (today_dt + timedelta(days=days_ahead)).isoformat()

    # Try dateparser for complex dates (last resort)
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
    Extract likely task title from user text, preserving exact wording.

    Examples:
        "add team meeting tomorrow" -> "team meeting"
        "schedule workout at 7am" -> "workout"
        "make Project Meeting 1 on Oct 29 at 1pm" -> "Project Meeting 1"
        "add HW session 2 tomorrow" -> "HW session 2"
    """
    original_text = text  # Keep original for case preservation
    text_lower = text.lower()

    # Step 1: Remove trigger words (case-insensitive)
    trigger_patterns = [
        r'\b(?:add|schedule|create|plan|book|make|set\s+up|set|remind\s+me\s+to|reminder|new)\b',
    ]
    for pattern in trigger_patterns:
        text_lower = re.sub(pattern, '', text_lower, flags=re.IGNORECASE)

    # Step 2: Remove time expressions with context (e.g., "at 7am", "at 1 pm")
    time_patterns = [
        r'\bat\s+\d{1,2}:\d{2}\s*(?:am|pm)?\b',  # at 7:30pm, at 14:00
        r'\bat\s+\d{1,2}\s*(?:am|pm)\b',         # at 1pm, at 7 am
        r'\bfrom\s+\d{1,2}:\d{2}\s*(?:am|pm)?\s*(?:to|-)\s*\d{1,2}:\d{2}\s*(?:am|pm)?\b',  # from 4pm to 6pm
    ]
    for pattern in time_patterns:
        text_lower = re.sub(pattern, '', text_lower, flags=re.IGNORECASE)

    # Step 3: Remove duration expressions with context (e.g., "for 2 hours")
    duration_patterns = [
        r'\bfor\s+\d+(?:\.\d+)?\s*(?:hours?|hrs?|h)\b',    # for 2 hours
        r'\bfor\s+\d+\s*(?:minutes?|mins?|m)\b',            # for 30 minutes
    ]
    for pattern in duration_patterns:
        text_lower = re.sub(pattern, '', text_lower, flags=re.IGNORECASE)

    # Step 4: Remove date expressions with context (e.g., "on Oct 29", "tomorrow")
    date_patterns = [
        r'\bon\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?\b',  # on Oct 29
        r'\bon\s+\d{1,2}/\d{1,2}(?:/\d{2,4})?\b',          # on 10/29 or 10/29/2025
        r'\b(?:next|this)\s+(?:week|month|year)\b',         # next week, this month
        r'\b(?:tomorrow|today|tonight)\b',                  # tomorrow, today
    ]
    for pattern in date_patterns:
        text_lower = re.sub(pattern, '', text_lower, flags=re.IGNORECASE)

    # Step 5: Remove day names with context (e.g., "on Monday", "every Thursday")
    text_lower = re.sub(r'\b(?:on|every|next|this)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)s?\b', '', text_lower, flags=re.IGNORECASE)

    # Step 6: Remove standalone leftover connector words
    connector_patterns = [
        r'\b(?:on|at|for|from|to|by|in|the|this|next|every)\b',
    ]
    for pattern in connector_patterns:
        text_lower = re.sub(pattern, ' ', text_lower, flags=re.IGNORECASE)

    # Step 7: Clean up whitespace
    text_lower = re.sub(r'\s+', ' ', text_lower).strip()

    if not text_lower:
        return "New Task"

    # Step 8: Find the preserved text in original (maintain original capitalization)
    # Build a regex from cleaned lowercase text to find it in original
    # We'll extract the same portion from the original text

    # Simple approach: find the position of the first and last word of cleaned text in original
    words = text_lower.split()
    if not words:
        return "New Task"

    # Try to find this phrase in the original text (case-insensitive search)
    # and return the original casing
    search_pattern = r'\b' + r'\s+'.join(re.escape(word) for word in words) + r'\b'
    match = re.search(search_pattern, original_text, flags=re.IGNORECASE)

    if match:
        return match.group(0).strip()

    # Fallback: capitalize each word from cleaned text
    return ' '.join(word.capitalize() for word in words)


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
