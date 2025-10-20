# --- Imports ---------------------------------------------------------------
import os
import streamlit as st
from datetime import datetime, timedelta, date, time
from zoneinfo import ZoneInfo
import json
import uuid
import re
from google import genai
from google.genai import types

# --- Page Configuration ----------------------------------------------------
st.set_page_config(
    page_title="TimeBuddy - Your Personal Time Assistant",
    page_icon="⏱️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS for TimeBuddy Theme ---------------------------------------
st.markdown("""
<style>
    /* Main theme colors */
    :root {
        --primary: #6366f1;
        --primary-dark: #4f46e5;
        --primary-light: #818cf8;
        --secondary: #22d3ee;
        --success: #10b981;
        --warning: #f59e0b;
        --danger: #ef4444;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%);
    }
    
    [data-testid="stSidebar"] .element-container {
        padding: 0.5rem;
    }
    
    /* Header styling */
    .main-header {
        background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 12px;
        margin-bottom: 2rem;
        box-shadow: 0 4px 12px rgba(99, 102, 241, 0.2);
    }
    
    /* Chat message styling */
    .user-message {
        background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
        color: white;
        padding: 0.75rem 1rem;
        border-radius: 12px;
        margin: 0.5rem 0;
        margin-left: 20%;
        box-shadow: 0 2px 8px rgba(99, 102, 241, 0.2);
    }
    
    .bot-message {
        background: #f1f5f9;
        color: #0f172a;
        padding: 0.75rem 1rem;
        border-radius: 12px;
        margin: 0.5rem 0;
        margin-right: 20%;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
    }
    
    /* Task card styling */
    .task-card {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1rem;
        margin: 0.5rem 0;
        transition: all 0.2s ease;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    }
    
    .task-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }
    
    .task-completed {
        background: #f0fdf4;
        border-color: var(--success);
    }
    
    /* Quick action buttons */
    .quick-action {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 20px;
        padding: 0.25rem 0.75rem;
        margin: 0.25rem;
        font-size: 0.875rem;
        transition: all 0.2s ease;
        cursor: pointer;
    }
    
    .quick-action:hover {
        background: var(--primary);
        color: white;
        border-color: var(--primary);
    }
    
    /* Calendar event styling */
    .event-work { background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%); }
    .event-meeting { background: linear-gradient(135deg, #f59e0b 0%, #dc2626 100%); }
    .event-personal { background: linear-gradient(135deg, #22d3ee 0%, #0891b2 100%); }
    .event-break { background: linear-gradient(135deg, #10b981 0%, #059669 100%); }
    
    /* Stats box */
    .stat-box {
        background: linear-gradient(135deg, rgba(99, 102, 241, 0.1) 0%, rgba(34, 211, 238, 0.1) 100%);
        border-radius: 12px;
        padding: 1rem;
        text-align: center;
    }
    
    .stat-number {
        font-size: 2rem;
        font-weight: bold;
        color: var(--primary);
    }
    
    .stat-label {
        color: #64748b;
        font-size: 0.875rem;
    }
</style>
""", unsafe_allow_html=True)

# --- Secrets and API Configuration ----------------------------------------
API_KEY = st.secrets.get("GEMINI_API_KEY", "")
if not API_KEY:
    st.error("⚠️ 'GEMINI_API_KEY' is not set in Streamlit secrets. Please add it in your Streamlit Cloud settings.")
    st.stop()

client = genai.Client(api_key=API_KEY)

# --- Identity / System Instructions ---------------------------------------
def load_developer_prompt() -> str:
    try:
        with open("identity.txt", "r") as f:
            return f.read()
    except FileNotFoundError:
        st.warning("⚠️ 'identity.txt' not found. Using default TimeBuddy personality.")
        return """
        You are TimeBuddy, a personal time management assistant. You help users:
        - Create and schedule tasks/events (PLAN_CREATE)
        - Edit existing schedules (PLAN_EDIT)
        - Check their agenda (PLAN_CHECK)
        - Manage their time effectively
        
        Be friendly, supportive, and focused on helping users manage their schedules.
        Always confirm before saving changes and provide clear feedback.
        """

system_instructions = load_developer_prompt()

# --- Initialize Session State ----------------------------------------------
if 'schedules' not in st.session_state:
    st.session_state.schedules = []
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'conversation_stage' not in st.session_state:
    st.session_state.conversation_stage = None
if 'pending_slots' not in st.session_state:
    st.session_state.pending_slots = {}
if 'message_input' not in st.session_state:
    st.session_state.message_input = ""
if 'clear_input' not in st.session_state:
    st.session_state.clear_input = False
if 'message_to_process' not in st.session_state:
    st.session_state.message_to_process = ""
if 'last_proposal' not in st.session_state:
    st.session_state.last_proposal = None
if 'tz_name' not in st.session_state:
    st.session_state.tz_name = "America/Phoenix"  # default TZ

# --- Helper Functions ------------------------------------------------------
def generate_id():
    """Generate unique ID for schedule entries"""
    return str(uuid.uuid4())[:8]

def get_tz() -> ZoneInfo:
    """Return the currently selected ZoneInfo timezone."""
    return ZoneInfo(st.session_state.get("tz_name", "America/Phoenix"))

def now_local() -> datetime:
    """Timezone-aware 'now' based on user’s selected timezone."""
    return datetime.now(get_tz())

def today_local() -> date:
    """Today's date in the selected timezone."""
    return now_local().date()

def parse_time_str(time_str):
    """Parse time string to datetime.time object"""
    try:
        time_str = time_str.strip().upper()
        if ":" in time_str:
            if "AM" in time_str or "PM" in time_str:
                return datetime.strptime(time_str, "%I:%M %p").time()
            else:
                return datetime.strptime(time_str, "%H:%M").time()
        elif "AM" in time_str or "PM" in time_str:
            return datetime.strptime(time_str, "%I%p").time()
        else:
            return datetime.strptime(time_str + ":00", "%H:%M").time()
    except:
        return None

def get_event_type(title):
    """Determine event type from title keywords"""
    title_lower = title.lower()
    if any(word in title_lower for word in ['meeting', 'standup', 'call', 'presentation']):
        return 'meeting'
    elif any(word in title_lower for word in ['break', 'lunch', 'coffee']):
        return 'break'
    elif any(word in title_lower for word in ['personal', 'gym', 'workout', 'appointment']):
        return 'personal'
    else:
        return 'work'

def add_schedule_entry(title, date_str, start_time, end_time=None, duration=None):
    """Add a new schedule entry"""
    entry = {
        'id': generate_id(),
        'title': title,
        'date': date_str,
        'start_time': start_time,
        'end_time': end_time,
        'duration': duration,
        'type': get_event_type(title),
        'completed': False,
        'created_at': now_local().isoformat()
    }
    st.session_state.schedules.append(entry)
    return entry

def get_today_schedules():
    """Get schedules for today (user-selected timezone)."""
    today_iso = today_local().isoformat()
    return [s for s in st.session_state.schedules if s['date'] == today_iso]

def get_week_schedules():
    """Get schedules for current week (user-selected timezone)."""
    today = today_local()
    start_week = today - timedelta(days=today.weekday())
    end_week = start_week + timedelta(days=6)
    
    week_schedules = []
    for s in st.session_state.schedules:
        schedule_date = datetime.fromisoformat(s['date']).date()
        if start_week <= schedule_date <= end_week:
            week_schedules.append(s)
    return week_schedules

def format_schedule_display(schedule):
    """Format schedule for display"""
    event_type_emoji = {
        'work': '💼',
        'meeting': '🤝',
        'personal': '🏃',
        'break': '☕'
    }
    
    emoji = event_type_emoji.get(schedule['type'], '📅')
    status = "✅" if schedule['completed'] else "⏰"
    
    time_str = f"{schedule['start_time']}"
    if schedule['end_time']:
        time_str += f" - {schedule['end_time']}"
    elif schedule['duration']:
        time_str += f" ({schedule['duration']} min)"
    
    return f"{status} {emoji} **{schedule['title']}** - {time_str}"

def get_schedules_summary():
    """Get a formatted summary of all schedules"""
    if not st.session_state.schedules:
        return "No schedules yet."
    
    summary = []
    for schedule in sorted(st.session_state.schedules, key=lambda x: (x['date'], x['start_time'])):
        date_obj = datetime.fromisoformat(schedule['date']).date()
        date_str = date_obj.strftime("%a, %b %d")
        status = "✅" if schedule['completed'] else "⏰"
        summary.append(f"- {status} {schedule['title']} on {date_str} at {schedule['start_time']}")
    
    return "\n".join(summary)

# ---------- Chat parsing helpers (robust saving) ----------
CONFIRM_TOKENS = ("yes", "y", "ok", "okay", "save", "confirm", "sure")

def _normalize_task_dict(d: dict) -> dict:
    """Ensure keys exist and types are sane."""
    title = d.get("title", "New Task")
    date_str = d.get("date", today_local().isoformat())
    start = d.get("start_time", "09:00")
    duration = d.get("duration", 60)
    try:
        duration = int(duration)
    except:
        duration = 60
    # compute end_time
    sh, sm = map(int, start.split(":"))
    end_m = sh*60 + sm + duration
    eh, em = divmod(end_m, 60)
    end = f"{eh:02d}:{em:02d}"
    return {"title": title, "date": date_str, "start_time": start, "duration": duration, "end_time": end}

def extract_task_json_after(label: str, text: str):
    """
    Try to extract JSON after a marker like 'TASK_ADD:'.
    Accepts plain JSON or fenced ```json blocks.
    """
    # fenced first
    m = re.search(rf"{label}\s*```json\s*(\{{.*?\}})\s*```", text, flags=re.S|re.I)
    if m:
        try:
            return json.loads(m.group(1))
        except:
            pass
    # simple brace capture (first object after label)
    m = re.search(rf"{label}\s*(\{{[^{{}}]*\}})", text, flags=re.S|re.I)
    if m:
        try:
            return json.loads(m.group(1))
        except:
            pass
    return None

def parse_task_from_texts(bot_text: str, user_text: str) -> dict:
    """
    Fallback heuristic if no structured JSON is present.
    """
    # Default scaffold
    task_info = {
        'title': None,
        'date': today_local().isoformat(),
        'start_time': None,
        'end_time': None,
        'duration': 60
    }
    lower = (user_text or "").lower()
    # Title guess
    title_patterns = [
        r'add\s+(.+?)\s+(?:at|on|tomorrow|today)',
        r'schedule\s+(.+?)\s+(?:at|for|tomorrow|today)',
        r'create\s+(.+?)\s+(?:at|for|tomorrow|today)',
        r'"([^"]+)"',
        r'task:\s*(.+?)(?:\s+at|\s+on|$)',
    ]
    for p in title_patterns:
        m = re.search(p, lower)
        if m:
            task_info['title'] = m.group(1).strip().title()
            break
    if not task_info['title']:
        for kw, title in (("meeting","Meeting"),("workout","Workout"),("gym","Workout"),("lunch","Lunch Break"),("study","Study Session")):
            if kw in lower:
                task_info['title'] = title; break
        if not task_info['title']:
            task_info['title'] = "New Task"
    # Date
    if "tomorrow" in lower:
        task_info['date'] = (today_local() + timedelta(days=1)).isoformat()
    elif "today" in lower:
        task_info['date'] = today_local().isoformat()
    else:
        days = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
        for dayname in days:
            if dayname in lower:
                today_d = today_local()
                target = days.index(dayname)
                ahead = target - today_d.weekday()
                if ahead <= 0: ahead += 7
                task_info['date'] = (today_d + timedelta(days=ahead)).isoformat()
                break
    # Time (simple)
    tm = re.search(r'at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', lower)
    if tm:
        hh = int(tm.group(1)); mm = int(tm.group(2) or 0)
        ampm = tm.group(3)
        if ampm == 'pm' and hh < 12: hh += 12
        if ampm == 'am' and hh == 12: hh = 0
        task_info['start_time'] = f"{hh:02d}:{mm:02d}"
    if not task_info['start_time']:
        task_info['start_time'] = "09:00"
    # Duration
    dm = re.search(r'(\d+)\s*(?:hours|hour|hrs|hr)', lower)
    if dm:
        task_info['duration'] = int(dm.group(1)) * 60
    else:
        dm = re.search(r'(\d+)\s*(?:mins|min|minutes|minute)', lower)
        if dm:
            task_info['duration'] = int(dm.group(1))
    # End time
    sh, sm = map(int, task_info['start_time'].split(":"))
    end_m = sh*60 + sm + task_info['duration']
    eh, em = divmod(end_m, 60)
    task_info['end_time'] = f"{eh:02d}:{em:02d}"
    return task_info

# --- Generation Configuration ---------------------------------------------
generation_cfg = types.GenerateContentConfig(
    system_instruction=system_instructions,
    temperature=0.7,
    max_output_tokens=2048,
)

# --- Sidebar Navigation ----------------------------------------------------
with st.sidebar:
    st.markdown('<div class="sidebar-header">', unsafe_allow_html=True)
    st.title("⏱️ TimeBuddy")
    st.caption("Your Personal Time Assistant")
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.divider()
    
    # User Profile
    st.markdown("### User Profile")
    st.markdown("👤 **User**")
    st.caption("Free Plan")
    
    st.divider()
    
    # About Section
    with st.expander("ℹ️ About TimeBuddy"):
        st.markdown("""
        **TimeBuddy** is your AI-powered personal time management assistant.
        
        ### How to Use:
        
        **Creating Tasks:**
        - "Add team meeting tomorrow at 2pm for 1 hour"
        - "Schedule workout at 7am"
        - "Block 2 hours for deep work"
        
        **Editing Tasks:**
        - "Move my workout to 8am"
        - "Cancel the 3pm meeting"
        - "Extend lunch break by 30 minutes"
        
        **Checking Schedule:**
        - "Show me today's schedule"
        - "What's on my calendar this week?"
        - "Do I have anything at 3pm?"
        
        **Tips:**
        - Use natural language - TimeBuddy understands context
        - Confirm before saving to avoid mistakes
        - Mark tasks complete by checking the box
        - Switch between Tasks, Calendar, and Analytics views
        
        **Version:** 1.0  
        **Powered by:** Gemini AI
        """)

    # --- Time & Timezone block ---
    st.divider()
    st.markdown("### 🕒 Time & Timezone")

    tz_options = [
        "UTC",
        "America/Phoenix", "America/Los_Angeles", "America/Denver",
        "America/Chicago", "America/New_York",
        "Europe/London", "Europe/Paris", "Europe/Berlin",
        "Asia/Seoul", "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata",
        "Australia/Sydney",
    ]
    initial_tz = st.session_state.tz_name
    if initial_tz not in tz_options:
        tz_options = [initial_tz] + tz_options

    selected_tz = st.selectbox("Timezone", tz_options, index=tz_options.index(initial_tz))
    st.session_state.tz_name = selected_tz

    current_time_container = st.empty()
    current_time_container.metric(
        label="Current time",
        value=now_local().strftime("%Y-%m-%d %H:%M"),
        delta=None
    )

    with st.expander("Add a custom timezone (IANA)"):
        custom = st.text_input("e.g., Europe/Amsterdam, America/Toronto")
        if custom:
            try:
                _ = ZoneInfo(custom)
                st.session_state.tz_name = custom
                st.success(f"Timezone set to {custom}")
                st.rerun()
            except Exception:
                st.error("Invalid IANA timezone. Try something like Europe/Paris or Asia/Singapore.")

# --- Main Content Area ---------------------------------------------------
# Header
st.markdown(f"""
<div class="main-header">
    <h1 style="margin: 0; color: white;">TimeBuddy Assistant</h1>
    <p style="margin: 0; opacity: 0.9;">Let's manage your schedule together!</p>
    <p style="margin: 0.25rem 0 0 0; opacity: 0.85;">Timezone: <b>{st.session_state.tz_name}</b> • Local time: <b>{now_local().strftime('%H:%M')}</b></p>
</div>
""", unsafe_allow_html=True)

# Create main layout columns
col_left, col_right = st.columns([2, 1])

with col_left:
    # Chat Interface
    st.markdown("### 💬 Chat Assistant")
    
    chat_container = st.container(height=400)
    with chat_container:
        # Show initial greeting if no history
        if not st.session_state.chat_history:
            st.markdown("""
            <div class="bot-message">
            👋 Hi! I'm TimeBuddy, your personal time assistant. I can help you:
            
            • **Schedule tasks**: "Add team meeting tomorrow at 2pm for 1 hour"<br>
            • **Edit plans**: "Move my workout to 7am"<br>
            • **Check agenda**: "Show me today's schedule"<br>
            • **Track progress**: Mark tasks as complete
            
            What would you like to do?
            </div>
            """, unsafe_allow_html=True)
        
        # Display chat messages
        for msg in st.session_state.chat_history:
            if msg['role'] == 'user':
                st.markdown(f'<div class="user-message">{msg["content"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="bot-message">{msg["content"]}</div>', unsafe_allow_html=True)
    
    # Quick action chips
    st.markdown("**Quick Commands:**")
    col1, col2, col3, col4 = st.columns(4)
    
    quick_actions = {
        "Add task": "Schedule a new task for me",
        "Show today": "What's on my schedule today?",
        "Edit schedule": "I need to change a task",
        "View week": "Show me this week's schedule"
    }
    
    for col, (label, command) in zip([col1, col2, col3, col4], quick_actions.items()):
        with col:
            if st.button(label, key=f"quick_{label}", use_container_width=True):
                st.session_state.pending_message = command
                st.rerun()
    
    # Input form
    with st.form(key="chat_form", clear_on_submit=True):
        default_text = st.session_state.get('pending_message', '')
        
        user_input = st.text_area(
            "Message TimeBuddy",
            placeholder="Try: 'Add team meeting tomorrow at 2pm for 1 hour' or 'Show me today's schedule'",
            height=80,
            value=default_text,
            key="msg_input_form"
        )
        
        col1, col2 = st.columns([1, 5])
        with col1:
            send_button = st.form_submit_button("📤 Send", use_container_width=True)
        with col2:
            pass
    
    # Clear chat button (outside form)
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.chat_history = []
        st.session_state.conversation_context = {}
        if 'pending_message' in st.session_state:
            del st.session_state.pending_message
        st.rerun()
    
    if 'pending_message' in st.session_state and default_text:
        del st.session_state.pending_message
    
    # -------------------- Process send --------------------
    if send_button and user_input.strip():
        st.session_state.chat_history.append({'role': 'user', 'content': user_input})
        
        # If user is confirming a pending proposal, save immediately
        if st.session_state.last_proposal and user_input.strip().lower().startswith(CONFIRM_TOKENS):
            data = _normalize_task_dict(st.session_state.last_proposal)
            add_schedule_entry(
                title=data["title"],
                date_str=data["date"],
                start_time=data["start_time"],
                end_time=data["end_time"],
                duration=data["duration"],
            )
            st.session_state.last_proposal = None
            st.session_state.chat_history.append({'role': 'bot', 'content': "Saved ✅ Your plan is on the calendar."})
            st.rerun()
        
        try:
            # Build conversation history for context
            conversation_text = ""
            for msg in st.session_state.chat_history[-5:]:
                role = "User" if msg['role'] == 'user' else "Assistant"
                conversation_text += f"{role}: {msg['content']}\n\n"
            
            # Prepare enhanced context with TimeBuddy identity and timezone-aware time
            context = f"""
            {system_instructions}
            
            Current schedules in the system:
            {get_schedules_summary()}
            
            Today's date: {today_local().isoformat()}
            Current day: {today_local().strftime("%A")}
            Current time: {now_local().strftime("%H:%M")}
            User timezone: {st.session_state.tz_name}
            
            Recent conversation:
            {conversation_text}
            
            Current user message: {user_input}
            
            Remember to follow the TimeBuddy conversation flow:
            1. For PLAN_CREATE: Collect title, time/date, and duration. Then ask "Save this?" for confirmation.
            2. For PLAN_EDIT: Identify the task and what changes to make.
            3. For PLAN_CHECK: Show the relevant schedule information.
            4. When user confirms saving, respond with "Saved ✅" and include a brief overview.
            
            If adding a task, include "TASK_ADD:" followed by JSON with title, date, start_time, duration.
            If editing a task, include "TASK_EDIT:" followed by JSON with id and changes.
            If deleting a task, include "TASK_DELETE:" followed by the task id.
            If marking complete, include "TASK_COMPLETE:" followed by the task id.
            """
            
            # Generate response
            response = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=[types.Content(parts=[types.Part(text=context)])],
                config=generation_cfg,
            )
            
            bot_response = response.text if response.text else "I understand. Let me help you with that."
            
            # ---- Save logic (robust) ----
            saved_now = False
            # 1) Structured immediate add
            task_json = extract_task_json_after("TASK_ADD:", bot_response) or extract_task_json_after("TASK_SAVE:", bot_response)
            if task_json:
                data = _normalize_task_dict(task_json)
                add_schedule_entry(
                    title=data["title"],
                    date_str=data["date"],
                    start_time=data["start_time"],
                    end_time=data["end_time"],
                    duration=data["duration"],
                )
                saved_now = True
                # strip protocol from bot text
                bot_response = re.sub(r'(TASK_ADD:|TASK_SAVE:)\s*```json.*?```', '', bot_response, flags=re.S|re.I)
                bot_response = re.sub(r'(TASK_ADD:|TASK_SAVE:)\s*\{[^{}]*\}', '', bot_response, flags=re.S|re.I)
            
            # 2) If model is proposing (asks to save), capture proposal
            if not saved_now:
                # Heuristic: if bot asks to confirm, try to parse a proposal from bot + user
                if re.search(r'\bsave this\?\b', bot_response, flags=re.I) or "confirm" in bot_response.lower():
                    # Prefer any structured payload
                    proposal = extract_task_json_after("TASK_PROPOSE:", bot_response) or task_json
                    if not proposal:
                        proposal = parse_task_from_texts(bot_response, user_input)
                    st.session_state.last_proposal = proposal
                    # Add our own little nudge
                    st.session_state.chat_history.append({'role': 'bot',
                        'content': "Please reply **yes** to save or **no** to cancel."})
                else:
                    # If user clearly asked to add and model might have responded casually, try immediate parse + save
                    if any(k in user_input.lower() for k in ['add','schedule','create','plan','book']) and "saved" in bot_response.lower():
                        proposal = extract_task_json_after("TASK_ADD:", bot_response) or parse_task_from_texts(bot_response, user_input)
                        data = _normalize_task_dict(proposal)
                        add_schedule_entry(
                            title=data["title"],
                            date_str=data["date"],
                            start_time=data["start_time"],
                            end_time=data["end_time"],
                            duration=data["duration"],
                        )
                        saved_now = True
            
            # 3) Completion / edit / delete passthroughs
            if "TASK_EDIT:" in bot_response:
                m = extract_task_json_after("TASK_EDIT:", bot_response)
                if m:
                    update_schedule_entry(m.get('id'), m)
                bot_response = re.sub(r'TASK_EDIT:\s*\{[^{}]*\}', '', bot_response, flags=re.S|re.I)
            if "TASK_DELETE:" in bot_response:
                m = re.search(r'TASK_DELETE:\s*([a-zA-Z0-9-]+)', bot_response)
                if m:
                    delete_schedule_entry(m.group(1))
                bot_response = re.sub(r'TASK_DELETE:\s*[a-zA-Z0-9-]+', '', bot_response)
            if "TASK_COMPLETE:" in bot_response:
                m = re.search(r'TASK_COMPLETE:\s*([a-zA-Z0-9-]+)', bot_response)
                if m:
                    mark_task_complete(m.group(1))
                bot_response = re.sub(r'TASK_COMPLETE:\s*[a-zA-Z0-9-]+', '', bot_response)
            
            # Append bot message
            st.session_state.chat_history.append({'role': 'bot', 'content': bot_response.strip()})
            
            # If we saved, force a refresh so right tabs reflect changes immediately
            if saved_now:
                st.rerun()
            
        except Exception as e:
            error_msg = f"Sorry, I encountered an error: {str(e)}"
            st.session_state.chat_history.append({'role': 'bot', 'content': error_msg})
        
        st.rerun()

with col_right:
    # Tab selection for different views
    view_tab = st.tabs(["📋 Tasks", "📅 Calendar", "📊 Analytics"])
    
    with view_tab[0]:
        # Tasks View - Today's Tasks and Week Overview
        st.markdown("### Today's Tasks")
        
        today_tasks = get_today_schedules()
        
        if today_tasks:
            for task in sorted(today_tasks, key=lambda x: x['start_time']):
                with st.container():
                    col1, col2 = st.columns([1, 4])
                    with col1:
                        checked = st.checkbox("", value=task['completed'], key=f"task_{task['id']}")
                        if checked != task['completed']:
                            task['completed'] = checked
                            st.rerun()
                    with col2:
                        st.markdown(format_schedule_display(task))
        else:
            st.info("No tasks scheduled for today. Add one using the chat!")
        
        st.divider()
        
        # Week Overview
        st.markdown("### This Week")
        week_tasks = get_week_schedules()
        
        if week_tasks:
            tasks_by_date = {}
            for task in week_tasks:
                tasks_by_date.setdefault(task['date'], []).append(task)
            
            for task_date in sorted(tasks_by_date.keys()):
                date_obj = datetime.fromisoformat(task_date).date()
                date_label = date_obj.strftime("%a, %b %d")
                
                with st.expander(f"**{date_label}** ({len(tasks_by_date[task_date])} tasks)"):
                    for task in sorted(tasks_by_date[task_date], key=lambda x: x['start_time']):
                        st.markdown(format_schedule_display(task))
        else:
            st.info("No tasks scheduled this week.")
    
    with view_tab[1]:
        # Calendar View
        st.markdown("### Weekly Calendar")
        
        # Get current week dates (timezone-aware)
        today = today_local()
        start_week = today - timedelta(days=today.weekday())
        week_dates = [start_week + timedelta(days=i) for i in range(7)]
        
        # Header
        cols = st.columns(7)
        for i, week_date in enumerate(week_dates):
            with cols[i]:
                day_name = week_date.strftime("%a")
                day_num = week_date.strftime("%d")
                is_today = week_date == today
                
                if is_today:
                    st.markdown(f"**{day_name}**  \n**{day_num}** 📍")
                else:
                    st.markdown(f"**{day_name}**  \n{day_num}")
        
        st.divider()
        
        # Display schedules for each day
        cols = st.columns(7)
        for i, week_date in enumerate(week_dates):
            with cols[i]:
                day_schedules = [s for s in st.session_state.schedules 
                                if s['date'] == week_date.isoformat()]
                
                if day_schedules:
                    for schedule in sorted(day_schedules, key=lambda x: x['start_time']):
                        event_color = {
                            'work': '🔵',
                            'meeting': '🟡',
                            'personal': '🟢',
                            'break': '⚪'
                        }.get(schedule['type'], '⚫')
                        
                        st.markdown(f"{event_color} {schedule['start_time'][:5]}")
                        st.caption(schedule['title'][:15] + ('...' if len(schedule['title']) > 15 else ''))
                else:
                    st.markdown("—")
    
    with view_tab[2]:
        # Analytics View
        st.markdown("### Time Analytics")
        
        total_scheduled = len(st.session_state.schedules)
        completed = len([s for s in st.session_state.schedules if s['completed']])
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Scheduled", total_scheduled)
            st.metric("Completion Rate", f"{(completed/total_scheduled*100 if total_scheduled > 0 else 0):.1f}%")
        
        with col2:
            st.metric("Completed", completed)
            st.metric("Pending", total_scheduled - completed)
        
        st.divider()
        
        # Task breakdown by type
        st.markdown("### Task Breakdown")
        task_types = {}
        for schedule in st.session_state.schedules:
            task_types[schedule['type']] = task_types.get(schedule['type'], 0) + 1
        
        if task_types:
            for task_type, count in task_types.items():
                emoji = {'work': '💼', 'meeting': '🤝', 'personal': '🏃', 'break': '☕'}.get(task_type, '📅')
                st.markdown(f"{emoji} **{task_type.capitalize()}**: {count} tasks")
        else:
            st.info("No data to display yet. Start scheduling tasks!")

# Footer
st.divider()
st.markdown("""
<div style="text-align: center; color: #94a3b8; font-size: 0.875rem;">
    TimeBuddy v1.0 | Powered by Gemini AI | Built with Streamlit
</div>
""", unsafe_allow_html=True)
