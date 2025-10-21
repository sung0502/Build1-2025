# app.py
"""
TimeBuddy - Modular AI Time Assistant
Uses Router + 4 specialized bots (Create, Edit, Check, Other)
"""
import re
import logging
import streamlit as st
from datetime import datetime, timedelta

# Setup logger for debugging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

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
    initial_sidebar_state="collapsed"
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
        display: none;
    }

    .top-nav {
        background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 12px rgba(99, 102, 241, 0.2);
        display: flex;
        align-items: center;
        justify-content: space-between;
    }

    .top-nav-left {
        display: flex;
        align-items: center;
        gap: 1.5rem;
    }

    .top-nav-center {
        display: flex;
        align-items: center;
        gap: 1rem;
    }

    .top-nav-right {
        display: flex;
        align-items: center;
        gap: 1rem;
    }

    .nav-title {
        font-size: 1.5rem;
        font-weight: 700;
        margin: 0;
    }

    .nav-time {
        font-size: 0.9rem;
        opacity: 0.95;
    }

    .nav-icon {
        cursor: pointer;
        padding: 0.5rem;
        border-radius: 8px;
        transition: background 0.2s;
    }

    .nav-icon:hover {
        background: rgba(255, 255, 255, 0.1);
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

    .section-header {
        background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
        padding: 1rem 1.5rem;
        border-radius: 10px;
        margin: 1rem 0 0.75rem 0;
        border-left: 4px solid var(--primary);
    }

    .section-header h3 {
        margin: 0;
        color: var(--primary-dark);
        font-size: 1.25rem;
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

        .top-nav {
            padding: 0.75rem 1rem;
            flex-direction: column;
            gap: 0.5rem;
        }

        .nav-title {
            font-size: 1.25rem;
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
    return llm, router, create_bot, edit_bot, check_bot, other_bot

llm, router, create_bot, edit_bot, check_bot, other_bot = init_brain()

# Store LLM in session state for smart confirmation handling
if 'llm' not in st.session_state:
    st.session_state.llm = llm

# Initialize modal states
if 'show_analytics' not in st.session_state:
    st.session_state.show_analytics = False
if 'show_help' not in st.session_state:
    st.session_state.show_help = False

# Timezone selector (hidden, but functional)
tz_options = [
    "America/Phoenix", "America/Los_Angeles", "America/Denver",
    "America/Chicago", "America/New_York", "Europe/London",
    "Europe/Paris", "Asia/Tokyo", "Asia/Shanghai", "UTC"
]

current_tz = st.session_state.tz_name
if current_tz not in tz_options:
    tz_options = [current_tz] + tz_options

# Top Navigation Bar
col_nav_left, col_nav_center, col_nav_right = st.columns([2, 3, 2])

with col_nav_left:
    st.markdown("""
    <div style="padding: 0.5rem 0;">
        <h2 style="margin: 0; color: var(--primary);">⏱️ TimeBuddy</h2>
        <p style="margin: 0; color: #64748b; font-size: 0.85rem;">Your Personal Time Assistant</p>
    </div>
    """, unsafe_allow_html=True)

with col_nav_center:
    selected_tz = st.selectbox(
        "Timezone",
        tz_options,
        index=tz_options.index(current_tz),
        key="tz_selector",
        label_visibility="collapsed"
    )
    st.session_state.tz_name = selected_tz

    st.markdown(f"""
    <div style="text-align: center; color: #64748b; font-size: 0.9rem; margin-top: -0.5rem;">
        🕒 {now_local(st.session_state).strftime('%Y-%m-%d %H:%M')}
    </div>
    """, unsafe_allow_html=True)

with col_nav_right:
    col_r1, col_r2 = st.columns(2)
    with col_r1:
        if st.button("📊 Analytics", key="nav_analytics", use_container_width=True):
            st.session_state.show_analytics = True
            st.rerun()
    with col_r2:
        if st.button("❓ Help", key="nav_help", use_container_width=True):
            st.session_state.show_help = True
            st.rerun()

st.divider()

# Main layout - Chat (33%) | Tasks & Calendar (67%)
col_left, col_right = st.columns([1, 2])

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
                    logger.info(f"🤖 Calling bot for stage: {route_decision.stage}")
                    if route_decision.stage == "PLAN_CREATE":
                        logger.info("   → CreateBot.run()")
                        envelope = create_bot.run(bot_request)
                    elif route_decision.stage == "PLAN_EDIT":
                        logger.info("   → EditBot.run()")
                        envelope = edit_bot.run(bot_request)
                    elif route_decision.stage == "PLAN_CHECK":
                        logger.info("   → CheckBot.run()")
                        envelope = check_bot.run(bot_request)
                    else:  # OTHER
                        logger.info("   → OtherBot.run()")
                        envelope = other_bot.run(bot_request)
                    logger.info(f"   ✅ Bot completed - returned envelope")

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
    # Tasks Section
    st.markdown('<div class="section-header"><h3>📋 Today\'s Tasks</h3></div>', unsafe_allow_html=True)

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

    # Week Tasks Expander
    with st.expander("📅 This Week's Tasks", expanded=False):
        week_tasks = get_week_schedules(st.session_state)

        if week_tasks:
            by_date = {}
            for t in week_tasks:
                by_date.setdefault(t['date'], []).append(t)

            for date_str in sorted(by_date.keys()):
                date_obj = datetime.fromisoformat(date_str).date()
                st.markdown(f"**{date_obj.strftime('%a, %b %d')}** ({len(by_date[date_str])} tasks)")
                for t in sorted(by_date[date_str], key=lambda x: x['start_time']):
                    st.markdown(f"  {format_schedule_display(t)}")
                st.markdown("")
        else:
            st.info("No tasks this week.")

    st.markdown("")  # Spacing

    # Calendar Section
    st.markdown('<div class="section-header"><h3>📅 Weekly Calendar</h3></div>', unsafe_allow_html=True)

    today = today_local(st.session_state)
    start_week = today - timedelta(days=today.weekday())
    week_dates = [start_week + timedelta(days=i) for i in range(7)]

    # Calendar header
    cols = st.columns(7)
    for i, d in enumerate(week_dates):
        with cols[i]:
            is_today = d == today
            st.markdown(f"**{d.strftime('%a')}**  \n{'📍' if is_today else ''}{d.strftime('%d')}")

    st.divider()

    # Calendar content
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

# Analytics Modal
if st.session_state.show_analytics:
    @st.dialog("📊 Time Analytics", width="large")
    def show_analytics_modal():
        total = len(st.session_state.schedules)
        completed = sum(1 for s in st.session_state.schedules if s['completed'])

        st.markdown("### 📈 Overview")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Tasks", total)
        with col2:
            st.metric("Completed", completed)
        with col3:
            st.metric("Pending", total - completed)
        with col4:
            st.metric("Completion Rate", f"{(completed/total*100 if total else 0):.0f}%")

        st.divider()

        st.markdown("### 🏷️ Task Breakdown by Type")
        types = {}
        for s in st.session_state.schedules:
            types[s['type']] = types.get(s['type'], 0) + 1

        if types:
            for t, c in types.items():
                emoji = {'work': '💼', 'meeting': '🤝', 'personal': '🏃', 'break': '☕'}.get(t, '📅')
                st.markdown(f"{emoji} **{t.capitalize()}**: {c} tasks")
        else:
            st.info("No tasks yet. Start adding tasks to see analytics!")

        st.divider()

        if st.button("Close", key="close_analytics", use_container_width=True):
            st.session_state.show_analytics = False
            st.rerun()

    show_analytics_modal()

# Help Modal
if st.session_state.show_help:
    @st.dialog("❓ Help & About", width="large")
    def show_help_modal():
        st.markdown("""
        ### 🤖 About TimeBuddy

        **TimeBuddy** is your AI-powered personal time assistant built with a modular architecture.

        ---

        ### 📝 How to Use

        #### Creating Tasks:
        - "Add team meeting tomorrow at 2pm"
        - "Schedule workout at 7am for 1 hour"
        - "Set up lunch with Sarah on Friday at noon"

        #### Editing Tasks:
        - "Move my workout to 8am"
        - "Cancel the meeting"
        - "Change the team meeting to 3pm"

        #### Checking Schedule:
        - "Show me today's schedule"
        - "What's on this week?"
        - "Do I have anything tomorrow?"

        ---

        ### 🔧 Features

        - **Smart AI Routing**: Automatically routes your requests to specialized bots
        - **Natural Language**: Talk to TimeBuddy like a personal assistant
        - **Multi-timezone Support**: Work across different time zones seamlessly
        - **Task Management**: Create, edit, check, and complete tasks with ease
        - **Visual Calendar**: See your week at a glance

        ---

        ### ℹ️ System Information

        - **Version:** 2.0 (Modular Architecture)
        - **AI Engine:** Gemini AI
        - **Framework:** Streamlit
        - **Architecture:** Router + Specialized Bots (Create, Edit, Check, Other)
        """)

        st.divider()

        if st.button("Close", key="close_help", use_container_width=True):
            st.session_state.show_help = False
            st.rerun()

    show_help_modal()

st.divider()
st.markdown("""
<div style="text-align: center; color: #94a3b8; font-size: 0.875rem;">
    TimeBuddy v2.0 (Modular) | Powered by Gemini AI | Built with Streamlit
</div>
""", unsafe_allow_html=True)
