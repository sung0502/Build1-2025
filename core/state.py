# core/state.py
"""
State management for TimeBuddy session.
Provides helpers for managing schedules, chat history, and confirmation flow.
"""
from datetime import datetime, date, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import uuid
import json
import os
from pathlib import Path


# Data persistence
DATA_DIR = Path("data")
SCHEDULES_FILE = DATA_DIR / "schedules.json"


def ensure_data_dir():
    """Ensure data directory exists."""
    DATA_DIR.mkdir(exist_ok=True)


def save_schedules(schedules: list[dict]) -> bool:
    """
    Save schedules to JSON file.

    Args:
        schedules: List of schedule dictionaries

    Returns:
        True if saved successfully, False otherwise
    """
    try:
        ensure_data_dir()
        with open(SCHEDULES_FILE, 'w') as f:
            json.dump(schedules, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving schedules: {e}")
        return False


def load_schedules() -> list[dict]:
    """
    Load schedules from JSON file.

    Returns:
        List of schedule dictionaries, or empty list if file doesn't exist
    """
    try:
        if SCHEDULES_FILE.exists():
            with open(SCHEDULES_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading schedules: {e}")
    return []


def detect_time_conflicts(schedules: list[dict], new_schedule: dict) -> list[dict]:
    """
    Detect conflicts between a new schedule and existing schedules.

    Args:
        schedules: Existing schedules
        new_schedule: New schedule to check

    Returns:
        List of conflicting schedules
    """
    conflicts = []
    new_date = new_schedule.get('date')
    new_start = new_schedule.get('start_time')
    new_end = new_schedule.get('end_time')

    if not all([new_date, new_start, new_end]):
        return conflicts

    for schedule in schedules:
        # Skip if different dates
        if schedule.get('date') != new_date:
            continue

        # Skip if same ID (editing existing task)
        if schedule.get('id') == new_schedule.get('id'):
            continue

        schedule_start = schedule.get('start_time')
        schedule_end = schedule.get('end_time')

        if not all([schedule_start, schedule_end]):
            continue

        # Check for overlap
        # Times overlap if: new_start < schedule_end AND new_end > schedule_start
        if new_start < schedule_end and new_end > schedule_start:
            conflicts.append(schedule)

    return conflicts


def calculate_end_time(start_time: str, duration: int) -> str:
    """
    Calculate end time from start time and duration, handling midnight overflow.

    Args:
        start_time: Start time in HH:MM format
        duration: Duration in minutes

    Returns:
        End time in HH:MM format (handles overflow past midnight)
    """
    h, m = map(int, start_time.split(":"))
    total_minutes = h * 60 + m + duration

    # Handle overflow past midnight
    end_h, end_m = divmod(total_minutes, 60)
    end_h = end_h % 24  # Wrap around at 24 hours

    return f"{end_h:02d}:{end_m:02d}"


def ensure_session_defaults(st_session_state):
    """Initialize session state with default values."""
    if 'schedules' not in st_session_state:
        # Load schedules from persistent storage
        st_session_state.schedules = load_schedules()
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
    # Calculate end_time if not provided (using new overflow-safe function)
    if not end_time:
        end_time = calculate_end_time(start_time, duration)

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

    # Save to persistent storage
    save_schedules(st_session_state.schedules)

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
            # Save to persistent storage
            save_schedules(st_session_state.schedules)
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
        # Save to persistent storage
        save_schedules(st_session_state.schedules)
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


def parse_corrective_info(st_session_state, user_text: str, current_proposal: dict) -> Optional[dict]:
    """
    Parse corrective information from user's response using LLM.

    Args:
        st_session_state: Session state containing LLM instance
        user_text: User's corrective message
        current_proposal: Current proposal being confirmed

    Returns:
        Dictionary with updated fields, or None if no corrections detected
    """
    # Import LLM from session state (it's initialized in app.py)
    if not hasattr(st_session_state, 'llm'):
        return None

    llm = st_session_state.llm

    system_instruction = """You are a smart assistant helping to parse corrective information from user messages.
When a user is being asked to confirm a plan and they provide corrective information instead of yes/no,
extract what they want to change.

Current proposal contains: title, date, start_time, duration, end_time

Analyze the user's message and return a JSON object with only the fields they want to update.
If the message contains corrective information, return the updated values.
If the message is just a yes/no or doesn't contain corrections, return an empty object {}.

Examples:
- "actually it's 4pm, not 2pm" -> {"start_time": "16:00"}
- "make it 30 minutes instead" -> {"duration": 30}
- "it should be tomorrow" -> {"date": "<tomorrow's date>"}
- "the title should be Client Call" -> {"title": "Client Call"}
- "change it to 3pm and make it 2 hours" -> {"start_time": "15:00", "duration": 120}

IMPORTANT:
- Use 24-hour format for times (e.g., "16:00" for 4pm)
- Use YYYY-MM-DD format for dates
- Duration should be in minutes
- Only include fields that are being corrected
- Return empty object {} if no corrections detected"""

    # Build context about current proposal and today's date
    today_str = today_local(st_session_state).isoformat()
    tomorrow = today_local(st_session_state) + timedelta(days=1)
    tomorrow_str = tomorrow.isoformat()

    prompt = f"""Current proposal:
- Title: {current_proposal.get('title')}
- Date: {current_proposal.get('date')}
- Start time: {current_proposal.get('start_time')}
- Duration: {current_proposal.get('duration')} minutes
- End time: {current_proposal.get('end_time')}

Today's date: {today_str}
Tomorrow's date: {tomorrow_str}

User's message: "{user_text}"

Extract corrective information as JSON:"""

    try:
        result = llm.classify_json(
            system_instruction=system_instruction,
            prompt=prompt
        )

        # If result is empty dict or None, no corrections detected
        if not result or (isinstance(result, dict) and len(result) == 0):
            return None

        return result
    except Exception:
        return None


def update_proposal_with_corrections(current_proposal: dict, corrections: dict) -> dict:
    """
    Update proposal with corrective information, recalculating end_time if needed.

    Args:
        current_proposal: Current proposal dict
        corrections: Dict with fields to update

    Returns:
        Updated proposal dict
    """
    updated = current_proposal.copy()
    updated.update(corrections)

    # Recalculate end_time if start_time or duration changed
    if 'start_time' in corrections or 'duration' in corrections:
        start_time = updated.get('start_time', '09:00')
        duration = updated.get('duration', 60)
        updated['end_time'] = calculate_end_time(start_time, duration)

    return updated


def try_handle_confirmation(st_session_state, user_text: str) -> bool:
    """
    Try to handle user confirmation response.
    Intelligently detects yes/no responses as well as corrective information.

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

    # Smart handling: Check if user is providing corrective information
    # instead of just yes/no
    corrections = parse_corrective_info(st_session_state, user_text, st_session_state.last_proposal)

    if corrections:
        # User provided corrective information - update the proposal and re-confirm
        updated_proposal = update_proposal_with_corrections(
            st_session_state.last_proposal,
            corrections
        )

        # Update the proposal in session state
        st_session_state.last_proposal = updated_proposal

        # Generate new confirmation message
        from datetime import datetime
        date_obj = datetime.fromisoformat(updated_proposal['date']).date()
        friendly_date = date_obj.strftime("%A, %B %d, %Y")

        confirmation_msg = f"Got it! Updated to **{updated_proposal['title']}** on {friendly_date} from {updated_proposal['start_time']} to {updated_proposal['end_time']} ({updated_proposal['duration']} minutes). Save this?"

        # Check for conflicts with updated time
        conflicts = detect_time_conflicts(st_session_state.schedules, updated_proposal)
        if conflicts:
            conflict_names = ", ".join([f"**{c['title']}**" for c in conflicts[:2]])
            if len(conflicts) > 2:
                conflict_names += f" and {len(conflicts) - 2} more"
            confirmation_msg = f"⚠️ **Time conflict detected!** This overlaps with: {conflict_names}\n\n{confirmation_msg}"

        push_bot(st_session_state, confirmation_msg)
        # Keep awaiting_confirmation=True with updated proposal
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
