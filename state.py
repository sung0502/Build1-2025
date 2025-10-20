# core/state.py
"""
State management for TimeBuddy session.
Provides helpers for managing schedules, chat history, and confirmation flow.
"""
from datetime import datetime, date, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import uuid


def ensure_session_defaults(st_session_state):
    """Initialize session state with default values."""
    if 'schedules' not in st_session_state:
        st_session_state.schedules = []
    if 'chat_history' not in st_session_state:
        st_session_state.chat_history = []
    if 'stage' not in st_session_state:
        st_session_state.stage = None
    if 'awaiting_confirmation' not in st_session_state:
        st_session_state.awaiting_confirmation = False
    if 'last_proposal' not in st_session_state:
        st_session_state.last_proposal = None
    if 'tz_name' not in st_session_state:
        st_session_state.tz_name = "America/Phoenix"
    if 'version' not in st_session_state:
        st_session_state.version = 0


def get_tz(st_session_state) -> ZoneInfo:
    """Get current timezone as ZoneInfo object."""
    return ZoneInfo(st_session_state.get("tz_name", "America/Phoenix"))


def now_local(st_session_state) -> datetime:
    """Get current datetime in user's timezone."""
    return datetime.now(get_tz(st_session_state))


def today_local(st_session_state) -> date:
    """Get today's date in user's timezone."""
    return now_local(st_session_state).date()


def generate_id() -> str:
    """Generate unique ID for schedule entries."""
    return str(uuid.uuid4())[:8]


def add_schedule(st_session_state, title: str, date_str: str, start_time: str, 
                 duration: int, end_time: Optional[str] = None) -> dict:
    """
    Add a new schedule entry.
    
    Args:
        st_session_state: Streamlit session state
        title: Task title
        date_str: Date in YYYY-MM-DD format
        start_time: Start time in HH:MM format
        duration: Duration in minutes
        end_time: Optional end time in HH:MM format
        
    Returns:
        Created schedule entry
    """
    # Calculate end_time if not provided
    if not end_time:
        h, m = map(int, start_time.split(":"))
        total_minutes = h * 60 + m + duration
        end_h, end_m = divmod(total_minutes, 60)
        end_time = f"{end_h:02d}:{end_m:02d}"
    
    entry = {
        'id': generate_id(),
        'title': title,
        'date': date_str,
        'start_time': start_time,
        'end_time': end_time,
        'duration': duration,
        'type': infer_event_type(title),
        'completed': False,
        'created_at': now_local(st_session_state).isoformat()
    }
    
    st_session_state.schedules.append(entry)
    st_session_state.version += 1
    return entry


def update_schedule(st_session_state, schedule_id: str, changes: dict) -> bool:
    """
    Update an existing schedule entry.
    
    Args:
        st_session_state: Streamlit session state
        schedule_id: ID of schedule to update
        changes: Dictionary of fields to update
        
    Returns:
        True if updated, False if not found
    """
    for schedule in st_session_state.schedules:
        if schedule['id'] == schedule_id:
            schedule.update(changes)
            st_session_state.version += 1
            return True
    return False


def delete_schedule(st_session_state, schedule_id: str) -> bool:
    """
    Delete a schedule entry.
    
    Args:
        st_session_state: Streamlit session state
        schedule_id: ID of schedule to delete
        
    Returns:
        True if deleted, False if not found
    """
    initial_len = len(st_session_state.schedules)
    st_session_state.schedules = [
        s for s in st_session_state.schedules if s['id'] != schedule_id
    ]
    if len(st_session_state.schedules) < initial_len:
        st_session_state.version += 1
        return True
    return False


def mark_complete(st_session_state, schedule_id: str) -> bool:
    """Mark a schedule as completed."""
    return update_schedule(st_session_state, schedule_id, {'completed': True})


def get_today_schedules(st_session_state) -> list[dict]:
    """Get schedules for today."""
    today_iso = today_local(st_session_state).isoformat()
    return [s for s in st_session_state.schedules if s['date'] == today_iso]


def get_week_schedules(st_session_state) -> list[dict]:
    """Get schedules for current week."""
    today = today_local(st_session_state)
    start_week = today - timedelta(days=today.weekday())
    end_week = start_week + timedelta(days=6)
    
    week_schedules = []
    for s in st_session_state.schedules:
        try:
            schedule_date = datetime.fromisoformat(s['date']).date()
            if start_week <= schedule_date <= end_week:
                week_schedules.append(s)
        except:
            continue
    
    return week_schedules


def format_schedule_display(schedule: dict) -> str:
    """Format a schedule entry for display."""
    event_type_emoji = {
        'work': '💼',
        'meeting': '🤝',
        'personal': '🏃',
        'break': '☕'
    }
    
    emoji = event_type_emoji.get(schedule.get('type', 'work'), '📅')
    status = "✅" if schedule.get('completed') else "⏰"
    
    time_str = schedule.get('start_time', '??:??')
    if schedule.get('end_time'):
        time_str += f" - {schedule['end_time']}"
    elif schedule.get('duration'):
        time_str += f" ({schedule['duration']} min)"
    
    return f"{status} {emoji} **{schedule['title']}** - {time_str}"


def schedules_snapshot_sorted(st_session_state) -> list[dict]:
    """Get sorted snapshot of all schedules for passing to bots."""
    return sorted(
        st_session_state.schedules,
        key=lambda x: (x.get('date', ''), x.get('start_time', ''))
    )


def push_user(st_session_state, text: str):
    """Add user message to chat history."""
    st_session_state.chat_history.append({'role': 'user', 'content': text})


def push_bot(st_session_state, text: str):
    """Add bot message to chat history."""
    st_session_state.chat_history.append({'role': 'bot', 'content': text})


def set_confirmation(st_session_state, proposal: dict, stage: str):
    """Set confirmation state with proposal."""
    st_session_state.awaiting_confirmation = True
    st_session_state.last_proposal = proposal
    st_session_state.stage = stage


def clear_confirmation(st_session_state):
    """Clear confirmation state."""
    st_session_state.awaiting_confirmation = False
    st_session_state.last_proposal = None


def try_handle_confirmation(st_session_state, user_text: str) -> bool:
    """
    Try to handle user confirmation response.
    
    Returns:
        True if confirmation was handled, False otherwise
    """
    if not st_session_state.awaiting_confirmation:
        return False
    
    text_lower = user_text.strip().lower()
    
    # Positive confirmations
    yes_tokens = ["yes", "y", "ok", "okay", "save", "confirm", "sure", "yep", "yeah", "👍", "✅"]
    if any(text_lower.startswith(token) for token in yes_tokens):
        proposal = st_session_state.last_proposal
        stage = st_session_state.stage
        
        if stage == "PLAN_CREATE" and proposal:
            # Create new schedule
            add_schedule(
                st_session_state,
                title=proposal.get('title', 'New Task'),
                date_str=proposal.get('date', today_local(st_session_state).isoformat()),
                start_time=proposal.get('start_time', '09:00'),
                duration=proposal.get('duration', 60),
                end_time=proposal.get('end_time')
            )
            push_bot(st_session_state, "Saved ✅ Your plan is on the calendar. What else can I help you with?")
        
        elif stage == "PLAN_EDIT" and proposal:
            # Apply edit
            if proposal.get('action') == 'delete':
                delete_schedule(st_session_state, proposal['id'])
                push_bot(st_session_state, "Saved ✅ Task deleted. What else can I help you with?")
            elif proposal.get('action') == 'complete':
                mark_complete(st_session_state, proposal['id'])
                push_bot(st_session_state, "Saved ✅ Task marked complete. What else can I help you with?")
            else:
                update_schedule(st_session_state, proposal['id'], proposal.get('changes', {}))
                push_bot(st_session_state, "Saved ✅ Task updated. What else can I help you with?")
        
        clear_confirmation(st_session_state)
        return True
    
    # Negative confirmations
    no_tokens = ["no", "n", "cancel", "nope", "nah", "nevermind", "👎", "❌"]
    if any(text_lower.startswith(token) for token in no_tokens):
        push_bot(st_session_state, "No problem! Discarded. What would you like to do instead?")
        clear_confirmation(st_session_state)
        return True
    
    # User said something else while waiting for confirmation
    # Remind them we need an answer
    push_bot(st_session_state, "I'm still waiting for your confirmation. Please reply **yes** to save or **no** to cancel.")
    return True


def infer_event_type(title: str) -> str:
    """Infer event type from title keywords."""
    title_lower = title.lower()
    if any(word in title_lower for word in ['meeting', 'standup', 'call', 'presentation', 'interview']):
        return 'meeting'
    elif any(word in title_lower for word in ['break', 'lunch', 'coffee', 'dinner', 'breakfast']):
        return 'break'
    elif any(word in title_lower for word in ['personal', 'gym', 'workout', 'appointment', 'exercise']):
        return 'personal'
    else:
        return 'work'
