# core/recurrence.py
"""
Recurring task pattern detection and expansion.
Handles patterns like "every Thursday", "every weekday", "daily", etc.
"""
import re
import uuid
from datetime import date, timedelta
from typing import Optional, List, Dict, Tuple


def detect_recurring_pattern(text: str) -> Optional[Dict]:
    """
    Detect if text contains a recurring pattern.

    Returns:
        Dict with pattern info if detected, None otherwise
        {
            'pattern_type': 'weekly|daily|weekdays|specific_days',
            'days': [0, 1, 2, ...],  # 0=Monday, 6=Sunday
            'interval': int,  # e.g., 1 for weekly, 2 for bi-weekly
            'timeframe': str,  # e.g., 'this month', 'for 4 weeks', 'until date'
            'raw_text': str
        }
    """
    text_lower = text.lower()

    # Check for recurring keywords
    recurring_keywords = ['every', 'daily', 'recurring', 'repeating', 'each']
    has_recurring = any(kw in text_lower for kw in recurring_keywords)

    if not has_recurring:
        return None

    pattern_info = {
        'pattern_type': None,
        'days': [],
        'interval': 1,
        'timeframe': None,
        'raw_text': text
    }

    # Pattern: "daily" or "every day"
    if 'daily' in text_lower or 'every day' in text_lower:
        pattern_info['pattern_type'] = 'daily'
        pattern_info['days'] = list(range(7))  # All days

    # Pattern: "every weekday" or "weekdays"
    elif 'weekday' in text_lower:
        pattern_info['pattern_type'] = 'weekdays'
        pattern_info['days'] = [0, 1, 2, 3, 4]  # Mon-Fri

    # Pattern: "every [day name]" or "every [day name]s"
    else:
        day_map = {
            'monday': 0, 'mon': 0,
            'tuesday': 1, 'tue': 1, 'tues': 1,
            'wednesday': 2, 'wed': 2,
            'thursday': 3, 'thu': 3, 'thurs': 3,
            'friday': 4, 'fri': 4,
            'saturday': 5, 'sat': 5,
            'sunday': 6, 'sun': 6
        }

        found_days = []
        for day_name, day_num in day_map.items():
            # Look for "every thursday" or "every thursdays"
            if re.search(r'\bevery\s+' + day_name + r's?\b', text_lower):
                if day_num not in found_days:
                    found_days.append(day_num)

            # Also check for "each thursday"
            if re.search(r'\beach\s+' + day_name + r's?\b', text_lower):
                if day_num not in found_days:
                    found_days.append(day_num)

        if found_days:
            pattern_info['pattern_type'] = 'specific_days'
            pattern_info['days'] = sorted(found_days)

    # If no pattern detected, return None
    if not pattern_info['pattern_type']:
        return None

    # Detect timeframe
    # Pattern: "for X weeks/months"
    week_match = re.search(r'for\s+(\d+)\s+weeks?', text_lower)
    if week_match:
        weeks = int(week_match.group(1))
        pattern_info['timeframe'] = f'for {weeks} weeks'

    # Pattern: "this month", "for this month"
    elif 'this month' in text_lower or 'for month' in text_lower:
        pattern_info['timeframe'] = 'this month'

    # Pattern: "until [date]"
    elif 'until' in text_lower:
        # Try to extract date after "until"
        until_match = re.search(r'until\s+([a-z0-9/\s]+)', text_lower)
        if until_match:
            pattern_info['timeframe'] = f"until {until_match.group(1).strip()}"

    return pattern_info


def expand_recurring_pattern(
    pattern_info: Dict,
    title: str,
    start_time: str,
    duration: int,
    end_time: str,
    today: date,
    max_occurrences: int = 30
) -> Tuple[List[Dict], Optional[str], Optional[str]]:
    """
    Expand a recurring pattern into individual task instances.

    Args:
        pattern_info: Pattern info from detect_recurring_pattern
        title: Task title
        start_time: Start time in HH:MM format
        duration: Duration in minutes
        end_time: End time in HH:MM format
        today: Current date
        max_occurrences: Maximum number of tasks to create

    Returns:
        Tuple of:
        - List of task dicts (without id, created_at, etc.)
        - Recurrence ID (UUID to link all tasks)
        - Timeframe description for confirmation message
    """
    if not pattern_info:
        return [], None, None

    pattern_type = pattern_info['pattern_type']
    days_of_week = pattern_info['days']
    timeframe = pattern_info['timeframe']

    # Generate recurrence ID
    recurrence_id = str(uuid.uuid4())

    # Determine end date for expansion
    end_date = None

    if timeframe:
        if 'this month' in timeframe:
            # End of current month
            if today.month == 12:
                end_date = date(today.year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date(today.year, today.month + 1, 1) - timedelta(days=1)

        elif 'for' in timeframe and 'week' in timeframe:
            # Extract weeks
            match = re.search(r'(\d+)\s+weeks?', timeframe)
            if match:
                weeks = int(match.group(1))
                end_date = today + timedelta(weeks=weeks)

        elif 'until' in timeframe:
            # Parse the date (simplified, could use dateparser)
            # For now, try common formats
            from core.timeparse import infer_date
            date_text = timeframe.replace('until', '').strip()
            try:
                end_date_str = infer_date(date_text, today)
                from datetime import datetime
                end_date = datetime.fromisoformat(end_date_str).date()
            except:
                # Default to 4 weeks
                end_date = today + timedelta(weeks=4)

    # If no timeframe specified, ask for clarification (handled by caller)
    if not end_date:
        return [], recurrence_id, "No timeframe specified"

    # Generate dates based on pattern
    task_dates = []
    current_date = today

    if pattern_type == 'daily':
        # Every day
        while current_date <= end_date and len(task_dates) < max_occurrences:
            task_dates.append(current_date)
            current_date += timedelta(days=1)

    elif pattern_type in ['weekdays', 'specific_days']:
        # Specific days of week
        while current_date <= end_date and len(task_dates) < max_occurrences:
            if current_date.weekday() in days_of_week:
                task_dates.append(current_date)
            current_date += timedelta(days=1)

    # Build task instances
    tasks = []
    for task_date in task_dates:
        task = {
            'title': title,
            'date': task_date.isoformat(),
            'start_time': start_time,
            'end_time': end_time,
            'duration': duration,
            'recurrence_id': recurrence_id
        }
        tasks.append(task)

    # Build timeframe description
    if task_dates:
        first_date = task_dates[0]
        last_date = task_dates[-1]
        timeframe_desc = f"{first_date.strftime('%b %d')} to {last_date.strftime('%b %d')}"
    else:
        timeframe_desc = "No matching dates"

    return tasks, recurrence_id, timeframe_desc


def format_recurring_dates(dates: List[date], max_show: int = 5) -> str:
    """
    Format a list of dates for display in confirmation message.

    Args:
        dates: List of date objects
        max_show: Maximum number of dates to show explicitly

    Returns:
        Formatted string like "Oct 23, Oct 30, Nov 6 (and 2 more)"
    """
    if not dates:
        return "no dates"

    formatted = []
    for d in dates[:max_show]:
        formatted.append(d.strftime('%b %d'))

    result = ", ".join(formatted)

    if len(dates) > max_show:
        remaining = len(dates) - max_show
        result += f" (and {remaining} more)"

    return result
