# --- Imports ---------------------------------------------------------------
import os
import streamlit as st
from datetime import datetime, timedelta, date, time
import json
import uuid
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

# --- Helper Functions -----------------------------------------------------
def generate_id():
    """Generate unique ID for schedule entries"""
    return str(uuid.uuid4())[:8]

def parse_time_str(time_str):
    """Parse time string to datetime.time object"""
    try:
        # Handle various formats: "2pm", "14:00", "2:30 PM"
        time_str = time_str.strip().upper()
        if ":" in time_str:
            if "AM" in time_str or "PM" in time_str:
                return datetime.strptime(time_str, "%I:%M %p").time()
            else:
                return datetime.strptime(time_str, "%H:%M").time()
        elif "AM" in time_str or "PM" in time_str:
            return datetime.strptime(time_str, "%I%p").time()
        else:
            # Assume 24-hour format
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
        'created_at': datetime.now().isoformat()
    }
    st.session_state.schedules.append(entry)
    return entry

def get_today_schedules():
    """Get schedules for today"""
    today = date.today().isoformat()
    return [s for s in st.session_state.schedules if s['date'] == today]

def get_week_schedules():
    """Get schedules for current week"""
    today = date.today()
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

# --- Generation Configuration ---------------------------------------------
generation_cfg = types.GenerateContentConfig(
    system_instruction=system_instructions,
    temperature=0.7,
    max_output_tokens=2048,
)

# --- Sidebar Navigation --------------------------------------------------
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


# --- Main Content Area ---------------------------------------------------
# Header
st.markdown("""
<div class="main-header">
    <h1 style="margin: 0; color: white;">TimeBuddy Assistant</h1>
    <p style="margin: 0; opacity: 0.9;">Let's manage your schedule together!</p>
</div>
""", unsafe_allow_html=True)

# Create main layout columns
col_left, col_right = st.columns([2, 1])

with col_left:
    # Chat Interface
    st.markdown("### 💬 Chat Assistant")
    
    # Display chat history
    chat_container = st.container(height=400)
    with chat_container:
        # Show initial greeting if no history
        if not st.session_state.chat_history:
            st.markdown("""
            <div class="bot-message">
            👋 Hi! I'm TimeBuddy, your personal time assistant. I can help you:
            
            • **Schedule tasks**: "Add team meeting tomorrow at 2pm for 1 hour"
            • **Edit plans**: "Move my workout to 7am"
            • **Check agenda**: "Show me today's schedule"
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
                st.session_state.chat_input = command
    
    # Chat input with clear functionality
    def on_send_click():
        if st.session_state.msg_input and st.session_state.msg_input.strip():
            # Store the message to process
            st.session_state.message_to_process = st.session_state.msg_input
            # Clear the input field
            st.session_state.msg_input = ""
    
    # Create text area that will be cleared after sending
    user_input = st.text_area(
        "Message TimeBuddy",
        placeholder="Try: 'Add team meeting tomorrow at 2pm for 1 hour' or 'Show me today's schedule'",
        height=80,
        key="msg_input"
    )
    
    col1, col2 = st.columns([1, 5])
    with col1:
        send_button = st.button("📤 Send", use_container_width=True, on_click=on_send_click, disabled=not user_input.strip())
    with col2:
        clear_button = st.button("🗑️ Clear Chat", use_container_width=True)
    
    if clear_button:
        st.session_state.chat_history = []
        st.session_state.conversation_context = {}  # Clear context
        st.session_state.message_to_process = ""
        st.rerun()
    
    # Process user input if there's a message to process
    if 'message_to_process' in st.session_state and st.session_state.message_to_process:
        user_message = st.session_state.message_to_process
        
        # Add user message to history
        st.session_state.chat_history.append({'role': 'user', 'content': user_message})
        
        # Clear the message after adding to history
        st.session_state.message_to_process = ""
        st.session_state.message_input = ""  # Reset the input field value
        
        try:
            # Build conversation history for context
            conversation_text = ""
            for msg in st.session_state.chat_history[-5:]:  # Last 5 messages for context
                role = "User" if msg['role'] == 'user' else "Assistant"
                conversation_text += f"{role}: {msg['content']}\n\n"
            
            # Prepare context with current state
            context = f"""
            You are TimeBuddy, a time management assistant. Help the user manage their schedule.
            
            Current schedules in the system:
            {json.dumps(st.session_state.schedules, indent=2) if st.session_state.schedules else "No schedules yet."}
            
            Today's date: {date.today().isoformat()}
            Current time: {datetime.now().strftime("%H:%M")}
            
            Recent conversation:
            {conversation_text}
            
            Current user message: {user_message}
            
            Instructions:
            - If the user wants to add a task/event, ask for any missing information (title, date/time, duration)
            - If the user confirms adding a task, respond with "CONFIRMED_ADD:" followed by the task details
            - If the user wants to edit/delete a task, help them identify which one
            - If the user wants to check their schedule, show them the relevant information
            - Be helpful and conversational
            """
            
            # Generate response
            response = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=[types.Content(parts=[types.Part(text=context)])],
                config=generation_cfg,
            )
            
            bot_response = response.text if response.text else "I understand. Let me help you with that."
            
            # Check if bot confirmed adding a task
            if "CONFIRMED_ADD:" in bot_response:
                # Parse the task details (simplified for now)
                # In a real implementation, you'd parse the details from the response
                
                # Example: Add a default task (you can enhance this parsing logic)
                add_schedule_entry(
                    title="New Task",
                    date_str=date.today().isoformat(),
                    start_time="09:00",
                    duration=60
                )
                
                # Clean the response to remove the CONFIRMED_ADD marker
                bot_response = bot_response.replace("CONFIRMED_ADD:", "✅ Task added successfully!")
            
            # Add bot response to history
            st.session_state.chat_history.append({'role': 'bot', 'content': bot_response})
            
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
                # Create task card
                status_icon = "✅" if task['completed'] else "⏰"
                card_class = "task-completed" if task['completed'] else "task-card"
                
                with st.container():
                    col1, col2 = st.columns([1, 4])
                    with col1:
                        # Toggle completion
                        if st.checkbox("", value=task['completed'], key=f"task_{task['id']}"):
                            task['completed'] = not task['completed']
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
            # Group by date
            tasks_by_date = {}
            for task in week_tasks:
                task_date = task['date']
                if task_date not in tasks_by_date:
                    tasks_by_date[task_date] = []
                tasks_by_date[task_date].append(task)
            
            # Display by date
            for task_date in sorted(tasks_by_date.keys()):
                date_obj = datetime.fromisoformat(task_date).date()
                date_label = date_obj.strftime("%a, %b %d")
                
                with st.expander(f"**{date_label}** ({len(tasks_by_date[task_date])} tasks)"):
                    for task in tasks_by_date[task_date]:
                        st.markdown(format_schedule_display(task))
        else:
            st.info("No tasks scheduled this week.")
    
    with view_tab[1]:
        # Calendar View
        st.markdown("### Weekly Calendar")
        
        # Get current week dates
        today = date.today()
        start_week = today - timedelta(days=today.weekday())
        week_dates = [start_week + timedelta(days=i) for i in range(7)]
        
        # Create calendar grid header
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
        
        # Calculate stats
        total_scheduled = len(st.session_state.schedules)
        completed = len([s for s in st.session_state.schedules if s['completed']])
        
        # Display metrics
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
            task_type = schedule['type']
            if task_type not in task_types:
                task_types[task_type] = 0
            task_types[task_type] += 1
        
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
