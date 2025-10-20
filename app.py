# app.py
"""
TimeBuddy - Modular AI Time Assistant
Uses Router + 4 specialized bots (Create, Edit, Check, Other)
"""
import re
import streamlit as st
from datetime import datetime, timedelta

# Core imports
from core.contracts import BotRequest
from core.llm import LLM
from core.state import (
    ensure_session_defaults, now_local, today_local,
    get_today_schedules, get_week_schedules, format_schedule_display,
    schedules_snapshot_sorted, push_user, push_bot, try_handle_confirmation
)

# Brain imports
from brain.router import Router
from brain.merge import handle_envelope
from brain.bots.plan_create import CreateBot
from brain.bots.plan_edit import EditBot
from brain.bots.plan_check import CheckBot
from brain.bots.other import OtherBot

# Page config
st.set_page_config(
    page_title="TimeBuddy - Your Personal Time Assistant",
    page_icon="⏱️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    :root {
        --primary: #6366f1;
        --primary-dark: #4f46e5;
        --success: #10b981;
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%);
    }

    .main-header {
        background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 12px;
        margin-bottom: 2rem;
        box-shadow: 0 4px 12px rgba(99, 102, 241, 0.2);
    }

    .user-message {
        background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
        color: white;
        padding: 0.75rem 1rem;
        border-radius: 12px;
        margin: 0.5rem 0;
        margin-left: 20%;
        word-wrap: break-word;
        overflow-wrap: break-word;
        max-width: 75%;
    }

    .bot-message {
        background: #f1f5f9;
        color: #0f172a;
        padding: 0.75rem 1rem;
        border-radius: 12px;
        margin: 0.5rem 0;
        margin-right: 20%;
        word-wrap: break-word;
        overflow-wrap: break-word;
        max-width: 75%;
    }

    .task-card {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1rem;
        margin: 0.5rem 0;
        transition: all 0.2s ease;
    }

    .task-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }

    /* Mobile responsive styles */
    @media (max-width: 768px) {
        .user-message {
            margin-left: 10%;
            max-width: 85%;
        }

        .bot-message {
            margin-right: 10%;
            max-width: 85%;
        }

        .main-header {
            padding: 1rem;
        }

        .main-header h1 {
            font-size: 1.5rem !important;
        }

        /* Make calendar columns more compact on tablets */
        [data-testid="column"] {
            padding: 0.25rem !important;
            font-size: 0.85rem;
        }
    }

    @media (max-width: 480px) {
        .user-message {
            margin-left: 5%;
            max-width: 90%;
        }

        .bot-message {
            margin-right: 5%;
            max-width: 90%;
        }

        /* Make calendar columns very compact on mobile */
        [data-testid="column"] {
            padding: 0.15rem !important;
            font-size: 0.75rem;
        }

        /* Reduce font size for calendar items */
        [data-testid="stMarkdownContainer"] p {
            font-size: 0.75rem;
            margin: 0.1rem 0;
        }

        /* Make buttons more compact */
        [data-testid="stButton"] button {
            padding: 0.25rem 0.5rem;
            font-size: 0.75rem;
        }
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
ensure_session_defaults(st.session_state)

# Load API key
API_KEY = st.secrets.get("GEMINI_API_KEY", "")
if not API_KEY:
    st.error("⚠️ GEMINI_API_KEY not set in Streamlit secrets.")
    st.stop()

# Load system identity
try:
    with open("identity.txt", "r") as f:
        system_identity = f.read()
except FileNotFoundError:
    system_identity = "You are TimeBuddy, a personal time assistant."

# Initialize LLM and bots
@st.cache_resource
def init_brain():
    """Initialize the modular brain (Router + Bots)."""
    llm = LLM(api_key=API_KEY)
    router = Router(llm)
    create_bot = CreateBot(llm)
    edit_bot = EditBot(llm)
    check_bot = CheckBot(llm)
    other_bot = OtherBot(llm)
    return router, create_bot, edit_bot, check_bot, other_bot

router, create_bot, edit_bot, check_bot, other_bot = init_brain()

# Sidebar
with st.sidebar:
    st.title("⏱️ TimeBuddy")
    st.caption("Your Personal Time Assistant")
    st.divider()
    
    st.markdown("### 👤 User Profile")
    st.markdown("**User** • Free Plan")
    st.divider()
    
    # Timezone selector
    st.markdown("### 🕒 Time & Timezone")
    tz_options = [
        "America/Phoenix", "America/Los_Angeles", "America/Denver",
        "America/Chicago", "America/New_York", "Europe/London",
        "Europe/Paris", "Asia/Tokyo", "Asia/Shanghai", "UTC"
    ]
    
    current_tz = st.session_state.tz_name
    if current_tz not in tz_options:
        tz_options = [current_tz] + tz_options
    
    selected_tz = st.selectbox(
        "Timezone",
        tz_options,
        index=tz_options.index(current_tz)
    )
    st.session_state.tz_name = selected_tz
    
    st.metric(
        "Current time",
        now_local(st.session_state).strftime("%Y-%m-%d %H:%M")
    )
    
    st.divider()
    
    with st.expander("ℹ️ About TimeBuddy"):
        st.markdown("""
        **TimeBuddy** is your AI-powered time assistant.
        
        **Creating Tasks:**
        - "Add team meeting tomorrow at 2pm"
        - "Schedule workout at 7am for 1 hour"
        
        **Editing Tasks:**
        - "Move my workout to 8am"
        - "Cancel the meeting"
        
        **Checking Schedule:**
        - "Show me today's schedule"
        - "What's on this week?"
        
        **Version:** 2.0 (Modular Architecture)  
        **Powered by:** Gemini AI
        """)

# Main header
st.markdown(f"""
<div class="main-header">
    <h1 style="margin: 0;">TimeBuddy Assistant</h1>
    <p style="margin: 0.25rem 0 0 0; opacity: 0.9;">
        Timezone: <b>{st.session_state.tz_name}</b> • 
        Local time: <b>{now_local(st.session_state).strftime('%H:%M')}</b>
    </p>
</div>
""", unsafe_allow_html=True)

# Main layout
col_left, col_right = st.columns([2, 1])

with col_left:
    st.markdown("### 💬 Chat Assistant")
    
    # Chat container - responsive height
    chat_container = st.container(height=500)
    with chat_container:
        if not st.session_state.chat_history:
            st.markdown("""
            <div class="bot-message">
            👋 Hi! I'm TimeBuddy, your personal time assistant. I can help you:
            
            • **Schedule tasks**: "Add team meeting tomorrow at 2pm"<br>
            • **Edit plans**: "Move my workout to 7am"<br>
            • **Check agenda**: "Show me today's schedule"
            
            What would you like to do?
            </div>
            """, unsafe_allow_html=True)
        
        for msg in st.session_state.chat_history:
            if msg['role'] == 'user':
                st.markdown(f'<div class="user-message">{msg["content"]}</div>', unsafe_allow_html=True)
            else:
                # Convert markdown **text** to HTML <strong>text</strong> for proper rendering
                content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', msg["content"])
                st.markdown(f'<div class="bot-message">{content}</div>', unsafe_allow_html=True)
    
    # Quick commands
    st.markdown("**Quick Commands:**")
    col1, col2, col3, col4 = st.columns(4)
    
    quick_actions = {
        "Add task": "Schedule a new task for me",
        "Show today": "What's on my schedule today?",
        "Edit task": "I need to change a task",
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
            placeholder="Try: 'Add team meeting tomorrow at 2pm' or 'Show today'",
            height=80,
            value=default_text,
            key="msg_input"
        )
        
        send_button = st.form_submit_button("📤 Send", use_container_width=True)
    
    if st.button("🗑️ Clear Chat"):
        st.session_state.chat_history = []
        st.rerun()
    
    if 'pending_message' in st.session_state:
        del st.session_state.pending_message
    
    # Process message
    if send_button and user_input.strip():
        push_user(st.session_state, user_input)

        # Try confirmation first
        if try_handle_confirmation(st.session_state, user_input):
            st.rerun()
        else:
            # Show loading indicator while processing
            with st.spinner("🤔 Thinking..."):
                try:
                    # Build bot request
                    bot_request = BotRequest(
                        user_text=user_input,
                        now_iso=now_local(st.session_state).isoformat(),
                        tz_name=st.session_state.tz_name,
                        schedules_snapshot=schedules_snapshot_sorted(st.session_state),
                        system_identity=system_identity,
                        chat_history=st.session_state.chat_history[-5:]
                    )

                    # Route to appropriate bot
                    route_decision = router.route(
                        user_input,
                        awaiting_confirmation=st.session_state.awaiting_confirmation
                    )

                    # Call appropriate bot
                    if route_decision.stage == "PLAN_CREATE":
                        envelope = create_bot.run(bot_request)
                    elif route_decision.stage == "PLAN_EDIT":
                        envelope = edit_bot.run(bot_request)
                    elif route_decision.stage == "PLAN_CHECK":
                        envelope = check_bot.run(bot_request)
                    else:  # OTHER
                        envelope = other_bot.run(bot_request)

                    # Apply envelope
                    needs_rerun = handle_envelope(st.session_state, envelope)

                    if needs_rerun:
                        st.rerun()
                    else:
                        st.rerun()  # Always rerun to show new message

                except Exception as e:
                    # Handle errors gracefully
                    error_msg = "😕 Oops! Something went wrong. Please try again or rephrase your request."

                    # Add more specific error messages for common issues
                    if "API" in str(e) or "quota" in str(e).lower():
                        error_msg = "⚠️ AI service is temporarily unavailable. Please try again in a moment."
                    elif "network" in str(e).lower() or "connection" in str(e).lower():
                        error_msg = "📡 Network error. Please check your connection and try again."

                    push_bot(st.session_state, error_msg)
                    st.rerun()

with col_right:
    tabs = st.tabs(["📋 Tasks", "📅 Calendar", "📊 Analytics"])
    
    with tabs[0]:
        st.markdown("### Today's Tasks")
        today_tasks = get_today_schedules(st.session_state)
        
        if today_tasks:
            for task in sorted(today_tasks, key=lambda x: x['start_time']):
                col1, col2 = st.columns([1, 4])
                with col1:
                    checked = st.checkbox("", value=task['completed'], key=f"cb_{task['id']}")
                    if checked != task['completed']:
                        task['completed'] = checked
                        st.rerun()
                with col2:
                    st.markdown(format_schedule_display(task))
        else:
            st.info("No tasks for today. Add one in the chat!")
        
        st.divider()
        st.markdown("### This Week")
        week_tasks = get_week_schedules(st.session_state)
        
        if week_tasks:
            by_date = {}
            for t in week_tasks:
                by_date.setdefault(t['date'], []).append(t)
            
            for date_str in sorted(by_date.keys()):
                date_obj = datetime.fromisoformat(date_str).date()
                with st.expander(f"{date_obj.strftime('%a, %b %d')} ({len(by_date[date_str])})"):
                    for t in sorted(by_date[date_str], key=lambda x: x['start_time']):
                        st.markdown(format_schedule_display(t))
        else:
            st.info("No tasks this week.")
    
    with tabs[1]:
        st.markdown("### Weekly Calendar")
        today = today_local(st.session_state)
        start_week = today - timedelta(days=today.weekday())
        week_dates = [start_week + timedelta(days=i) for i in range(7)]
        
        cols = st.columns(7)
        for i, d in enumerate(week_dates):
            with cols[i]:
                is_today = d == today
                st.markdown(f"**{d.strftime('%a')}**  \n{'📍' if is_today else ''}{d.strftime('%d')}")
        
        st.divider()
        
        cols = st.columns(7)
        for i, d in enumerate(week_dates):
            with cols[i]:
                day_tasks = [s for s in st.session_state.schedules if s['date'] == d.isoformat()]
                if day_tasks:
                    for s in sorted(day_tasks, key=lambda x: x['start_time']):
                        emoji = {'work': '🔵', 'meeting': '🟡', 'personal': '🟢', 'break': '⚪'}.get(s['type'], '⚫')
                        st.markdown(f"{emoji} {s['start_time'][:5]}")
                        st.caption(s['title'][:15])
                else:
                    st.markdown("—")
    
    with tabs[2]:
        st.markdown("### Time Analytics")
        total = len(st.session_state.schedules)
        completed = sum(1 for s in st.session_state.schedules if s['completed'])
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Tasks", total)
            st.metric("Completion Rate", f"{(completed/total*100 if total else 0):.0f}%")
        with col2:
            st.metric("Completed", completed)
            st.metric("Pending", total - completed)
        
        st.divider()
        st.markdown("### Task Breakdown")
        types = {}
        for s in st.session_state.schedules:
            types[s['type']] = types.get(s['type'], 0) + 1
        
        if types:
            for t, c in types.items():
                emoji = {'work': '💼', 'meeting': '🤝', 'personal': '🏃', 'break': '☕'}.get(t, '📅')
                st.markdown(f"{emoji} **{t.capitalize()}**: {c}")

st.divider()
st.markdown("""
<div style="text-align: center; color: #94a3b8; font-size: 0.875rem;">
    TimeBuddy v2.0 (Modular) | Powered by Gemini AI | Built with Streamlit
</div>
""", unsafe_allow_html=True)
