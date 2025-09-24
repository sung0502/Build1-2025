# timebuddy_app.py
# Streamlit UI for "TimeBuddy" with stage routing, slot-filling, confirmations, and an in-memory agenda.

from __future__ import annotations
import re
import uuid
from datetime import datetime, timedelta, date, time
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd
import streamlit as st
from dateutil import parser as du_parser
from zoneinfo import ZoneInfo


# ----------------------------
# Page config & basic styling
# ----------------------------
st.set_page_config(page_title="TimeBuddy", page_icon="🕑", layout="wide")

PRIMARY_TZ = "America/Los_Angeles"

CUSTOM_CSS = """
<style>
/* Tidy up the chat area spacing */
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
/* Little badge styles */
.badge {
  display:inline-block; padding:2px 8px; border-radius:12px; font-size:0.75rem; font-weight:600;
  background:#EEF2FF; color:#3730A3; border:1px solid #C7D2FE;
}
.rule-note { font-size:0.85rem; color:#4B5563; }
caption, .small { font-size:0.85rem; color:#6B7280; }
.agenda-card {
  border:1px solid #E5E7EB; border-radius:12px; padding:12px; margin-bottom:10px; background:#FFFFFF;
  box-shadow: 0 1px 1px rgba(0,0,0,0.02);
}
.agenda-title { font-weight:600; }
.kbd { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
       background:#F3F4F6; border:1px solid #E5E7EB; border-radius:6px; padding:2px 6px; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ----------------------------
# Identity (summary for sidebar)
# ----------------------------
ROLE = (
    "You are TimeBuddy, a personal assistant created by Sung Park. "
    "You reduce friction in time management by automating planning, editing, and checking schedules."
)
GOAL = (
    "Help users save and load schedules and follow through. Learn habits to suggest better time blocks."
)

TRIGGERS = {
    "PLAN_CREATE": ["add", "plan", "schedule", "set", "block", "create", "make", "remind", "reminder", "start", "new", "routine"],
    "PLAN_EDIT":   ["move", "reschedule", "change", "shift", "delay", "extend", "shorten", "rename", "delete", "cancel"],
    "PLAN_CHECK":  ["show", "what's", "whats", "view", "list", "agenda", "calendar", "due", "status", "done", "today", "tomorrow", "week"],
    "OTHER":       ["help", "settings", "timezone", "role", "rules", "policy", "how you work", "chit", "chat"]
}

YES_PATTERNS = {"yes","y","yeah","yep","sure","ok","okay","confirm","do it","save","✅","👍"}
NO_PATTERNS  = {"no","n","nope","cancel","don’t","dont","stop","not now","❌"}

# ----------------------------
# State Model
# ----------------------------
@dataclass
class PendingOperation:
    type: Optional[str] = None  # "create" | "edit" | "check"
    target_id: Optional[str] = None

@dataclass
class Proposal:
    title: str
    date: date
    start: time
    end: time
    duration_min: int

@dataclass
class StateModel:
    stage: Optional[str] = None  # "PLAN_CREATE" | "PLAN_EDIT" | "PLAN_CHECK" | "OTHER" | None
    required_slots: Dict[str, Optional[str]] = None  # title, time_date, duration
    filled_slots: Dict[str, Optional[str]] = None
    pending_operation: PendingOperation = PendingOperation()
    awaiting_confirmation: bool = False
    last_proposal: Optional[Proposal] = None
    confidence: float = 1.0

def init_session():
    if "tz_str" not in st.session_state:
        st.session_state.tz_str = PRIMARY_TZ
    if "model" not in st.session_state:
        st.session_state.model = StateModel(
            stage=None,
            required_slots={"title": None, "time_date": None, "duration": None},
            filled_slots={"title": None, "time_date": None, "duration": None},
        )
    if "agenda" not in st.session_state:
        st.session_state.agenda = []  # list of dicts: id, title, date, start, end, duration_min, done
    if "messages" not in st.session_state:
        st.session_state.messages = []  # chat history


init_session()

def now_tz() -> datetime:
    return datetime.now(ZoneInfo(st.session_state.tz_str))

def parse_yes_no(txt: str) -> Optional[bool]:
    t = txt.strip().lower()
    if t in YES_PATTERNS: return True
    if t in NO_PATTERNS: return False
    return None

# ----------------------------
# Natural language parsing (lightweight, heuristic)
# ----------------------------
WEEKDAYS = {  # english -> weekday index
    "monday":0,"mon":0,"tuesday":1,"tue":1,"tues":1,"wednesday":2,"wed":2,
    "thursday":3,"thu":3,"thur":3,"thurs":3,"friday":4,"fri":4,"saturday":5,"sat":5,"sunday":6,"sun":6
}

def next_weekday(d: date, weekday: int) -> date:
    days_ahead = weekday - d.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return d + timedelta(days=days_ahead)

def infer_date(text: str, base_dt: datetime) -> date:
    t = text.lower()
    if "today" in t: return base_dt.date()
    if "tonight" in t: return base_dt.date()
    if "tomorrow" in t or "tmr" in t or "tmrw" in t: return (base_dt + timedelta(days=1)).date()
    # weekday name
    for wd_str, wd_idx in WEEKDAYS.items():
        if re.search(rf"\b{wd_str}\b", t):
            return next_weekday(base_dt.date(), wd_idx) if base_dt.date().weekday()!=wd_idx else base_dt.date()
    # Date-like strings: try dateutil
    try:
        dt = du_parser.parse(text, fuzzy=True, default=base_dt)
        return dt.date()
    except Exception:
        return base_dt.date()

def parse_time_range(text: str) -> Optional[Tuple[time, time]]:
    """
    Accepts formats like:
    - 7-9
    - 7–9
    - 7pm-9pm
    - 7:15 to 8:45
    - 19:00-21:00
    """
    t = text.lower().replace("—", "-").replace("–","-").replace("–","-").replace(" to ", "-")
    # pattern: h[:mm][am/pm]? - h[:mm][am/pm]?
    m = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*-\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', t)
    if not m:
        return None
    h1, m1, ap1, h2, m2, ap2 = m.groups()
    h1, h2 = int(h1), int(h2)
    m1 = int(m1) if m1 else 0
    m2 = int(m2) if m2 else 0

    def to_24h(h, mm, ap):
        if ap == "am":
            if h == 12: h = 0
        elif ap == "pm":
            if h != 12: h += 12
        return time(hour=h, minute=mm)

    if ap1 or ap2:
        t1 = to_24h(h1,m1,ap1)
        t2 = to_24h(h2,m2,ap2)
    else:
        # If no am/pm, assume 24h if > 12 else assume same-day sensible:
        # If "tonight" is present, bias to evening by adding 12 to small hours if needed.
        t1 = time(hour=h1 if h1>=8 else h1, minute=m1)
        t2 = time(hour=h2 if h2>=8 else h2, minute=m2)

    return t1, t2

def parse_duration(text: str) -> Optional[int]:
    """
    Returns minutes. Accept:
      "for 90 minutes", "for 1h 30m", "1h", "2 hours", "45 min"
    """
    t = text.lower()
    m = re.search(r'(\d+)\s*(h|hour|hours)\s*(\d+)?\s*(m|min|mins|minutes)?', t)
    if m:
        h = int(m.group(1))
        m2 = int(m.group(3)) if m.group(3) else 0
        return h*60 + m2

    m = re.search(r'(\d+)\s*(m|min|mins|minutes)\b', t)
    if m:
        return int(m.group(1))

    m = re.search(r'for\s+(\d+)\s*(m|min|mins|minutes)\b', t)
    if m:
        return int(m.group(1))

    m = re.search(r'for\s+(\d+)\s*(h|hour|hours)\b', t)
    if m:
        return int(m.group(1)) * 60

    return None

def normalize_times(text: str, base_dt: datetime) -> Tuple[Optional[date], Optional[time], Optional[time], Optional[int]]:
    d = infer_date(text, base_dt)
    rng = parse_time_range(text)
    dur = parse_duration(text)
    start_t, end_t = (rng if rng else (None, None))
    if rng and not dur:
        # compute duration
        start_dt = datetime.combine(d, start_t)
        end_dt = datetime.combine(d, end_t)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
        dur = int((end_dt - start_dt).total_seconds() // 60)
    return d, start_t, end_t, dur

def extract_title_guess(text: str, already_removed: str = "") -> Optional[str]:
    """
    Heuristic: take chunk around verbs like add/plan/schedule/move before/after time.
    If we have a time range like "7-9 tonight", remove it and use remaining words as title.
    """
    t = text
    # Remove obvious command verbs
    t = re.sub(r'\b(add|plan|schedule|set|block|create|make|remind|reminder|start|new)\b', '', t, flags=re.I)
    t = re.sub(r'\b(move|reschedule|change|shift|delay|extend|shorten|rename|delete|cancel)\b', '', t, flags=re.I)
    # Remove date/time fragments we recognized (rough)
    t = re.sub(r'\b(today|tonight|tomorrow|tmr|this week|next week|mon(day)?|tue(s|sday)?|wed(nesday)?|thu(r|rs|rsday)?|fri(day)?|sat(urday)?|sun(day)?)\b', '', t, flags=re.I)
    t = re.sub(r'\d{1,2}:\d{2}', '', t)
    t = re.sub(r'\d{1,2}\s*(am|pm)\b', '', t, flags=re.I)
    t = re.sub(r'\d{1,2}\s*[-–]\s*\d{1,2}', '', t)
    t = re.sub(r'for\s+\d+(\s*(min|mins|minutes|h|hour|hours))?', '', t, flags=re.I)
    t = re.sub(r'\s+', ' ', t).strip(' ,.-')
    return t if t else None


# ----------------------------
# Stage Routing
# ----------------------------
def classify_stage(user_text: str) -> Tuple[str, float]:
    t = user_text.lower()
    score = {"PLAN_CREATE":0, "PLAN_EDIT":0, "PLAN_CHECK":0, "OTHER":0}

    for stage, words in TRIGGERS.items():
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", t):
                score[stage] += 1

    # Choose highest
    stage = max(score, key=score.get)
    confidence = min(1.0, 0.4 + 0.2*score[stage])
    # Fallback: if none matched, try inference by shapes
    if all(v==0 for v in score.values()):
        # If just a time question, treat as CHECK
        if re.search(r'\btoday|tomorrow|week\b', t):
            stage, confidence = "PLAN_CHECK", 0.65
        else:
            stage, confidence = "PLAN_CREATE", 0.55  # bias to create for bare "study 7-9 tonight"
    return stage, confidence


# ----------------------------
# Agenda helpers (in-memory)
# ----------------------------
def save_agenda_item(p: Proposal) -> Dict[str, Any]:
    item = {
        "id": uuid.uuid4().hex[:8],
        "title": p.title.strip(),
        "date": p.date.isoformat(),
        "start": p.start.strftime("%H:%M"),
        "end": p.end.strftime("%H:%M"),
        "duration_min": p.duration_min,
        "done": False,
    }
    st.session_state.agenda.append(item)
    return item

def find_items_by_title_fragment(fragment: str) -> List[Dict[str, Any]]:
    frag = fragment.lower()
    return [it for it in st.session_state.agenda if frag in it["title"].lower()]

def format_overview(p: Proposal) -> str:
    return f"{p.title} — {p.date.strftime('%a, %b %d %Y')}, {p.start.strftime('%H:%M')}–{p.end.strftime('%H:%M')}."

def present_agenda(range_key: str = "today"):
    tznow = now_tz()
    if range_key == "today":
        d = tznow.date().isoformat()
        items = [it for it in st.session_state.agenda if it["date"] == d]
        label = f"Agenda for Today ({tznow.date().strftime('%a, %b %d')})"
    elif range_key == "tomorrow":
        d = (tznow + timedelta(days=1)).date().isoformat()
        items = [it for it in st.session_state.agenda if it["date"] == d]
        label = f"Agenda for Tomorrow ({(tznow+timedelta(days=1)).date().strftime('%a, %b %d')})"
    else:  # week
        start = tznow.date()
        end = start + timedelta(days=6)
        items = [it for it in st.session_state.agenda if start <= du_parser.parse(it["date"]).date() <= end]
        label = f"This Week ({start.strftime('%b %d')} – {end.strftime('%b %d')})"

    st.markdown(f"**{label}**")
    if not items:
        st.write("No items yet.")
        return

    # Sort by date, then start
    items_sorted = sorted(items, key=lambda x: (x["date"], x["start"]))

    for it in items_sorted:
        with st.container():
            st.markdown(
                f"<div class='agenda-card'>"
                f"<div class='agenda-title'>{it['title']}</div>"
                f"<div class='small'>{du_parser.parse(it['date']).strftime('%a, %b %d')} • {it['start']}–{it['end']} • {it['duration_min']} min</div>"
                f"<div class='small'>Status: {'✅ Done' if it['done'] else '⏳ Pending'}</div>"
                f"</div>",
                unsafe_allow_html=True
            )
            cols = st.columns([1,1,1,3])
            if cols[0].button(f"Mark done", key=f"done-{it['id']}"):
                it["done"] = True
                st.experimental_rerun()
            if cols[1].button("Delete", key=f"del-{it['id']}"):
                st.session_state.agenda = [x for x in st.session_state.agenda if x["id"] != it["id"]]
                st.experimental_rerun()
            with cols[2]:
                # Quick move: +30 minutes
                if st.button("+30 min", key=f"plus30-{it['id']}"):
                    start_dt = du_parser.parse(f"{it['date']} {it['start']}")
                    end_dt = du_parser.parse(f"{it['date']} {it['end']}")
                    start_dt += timedelta(minutes=30)
                    end_dt += timedelta(minutes=30)
                    it["start"] = start_dt.strftime("%H:%M")
                    it["end"] = end_dt.strftime("%H:%M")
                    st.experimental_rerun()


# ----------------------------
# Core handlers (Stages)
# ----------------------------
def handle_confirmation(user_text: str):
    m = st.session_state.model
    yn = parse_yes_no(user_text)
    if yn is None:
        # While awaiting confirmation, ignore routing words and seek YES/NO
        assistant(f"Please reply with **yes** to save or **no** to discard.", stage_hint=True)
        return
    if yn is True:
        # Save last_proposal
        item = save_agenda_item(m.last_proposal)
        assistant("Saved ✅\n\nOverview: " + format_overview(m.last_proposal) + "\n\nWhat else can I help you with?")
        # reset
        st.session_state.model = StateModel(
            stage=None,
            required_slots={"title": None, "time_date": None, "duration": None},
            filled_slots={"title": None, "time_date": None, "duration": None},
        )
    else:
        assistant("Okay, I won’t save that.\n\nWhat would you like to do next?")
        # reset
        st.session_state.model = StateModel(
            stage=None,
            required_slots={"title": None, "time_date": None, "duration": None},
            filled_slots={"title": None, "time_date": None, "duration": None},
        )

def route_to_stage(user_text: str):
    stage, conf = classify_stage(user_text)
    # Don’t route if we’re in slot-filling for PLAN_CREATE unless user restates details
    m = st.session_state.model
    if m.awaiting_confirmation:
        handle_confirmation(user_text)
        return

    # If in active stage with missing slots for PLAN_CREATE, stay there
    if m.stage == "PLAN_CREATE" and (m.required_slots["title"] is None or m.required_slots["time_date"] is None or m.required_slots["duration"] is None):
        handle_plan_create(user_text, stay_in_stage=True)
        return

    # Otherwise transition
    st.session_state.model.stage = stage
    st.session_state.model.confidence = conf
    assistant(f"Entering **{stage}** stage.", stage_hint=True)

    if conf < 0.6:
        assistant("I think you're trying to schedule something. Could you share the **title**, **time/date**, and **duration**?", stage_hint=True)
        return

    if stage == "PLAN_CREATE":
        handle_plan_create(user_text)
    elif stage == "PLAN_EDIT":
        handle_plan_edit(user_text)
    elif stage == "PLAN_CHECK":
        handle_plan_check(user_text)
    else:
        handle_other(user_text)

def handle_plan_create(user_text: str, stay_in_stage: bool = False):
    m = st.session_state.model
    if not stay_in_stage:
        # attempt to fill directly from message
        # 1) time/date + duration
        d, start_t, end_t, dur = normalize_times(user_text, now_tz())
        if d and (start_t and end_t):
            m.required_slots["time_date"] = f"{d.isoformat()} {start_t.strftime('%H:%M')}-{end_t.strftime('%H:%M')}"
            m.filled_slots["time_date"] = m.required_slots["time_date"]
        if dur:
            m.required_slots["duration"] = f"{dur}"
            m.filled_slots["duration"] = m.required_slots["duration"]
        # 2) title guess
        title_guess = extract_title_guess(user_text)
        if title_guess and len(title_guess) >= 2:
            m.required_slots["title"] = title_guess
            m.filled_slots["title"] = title_guess

    # Ask for missing slots in order
    if m.required_slots["title"] is None:
        assistant("Got it—what’s the **title** of this block?", stage_hint=True)
        return
    if m.required_slots["time_date"] is None:
        assistant("Great. When should it happen? (e.g., *tomorrow 7-9pm*, *Fri 08:00-09:00*)", stage_hint=True)
        return
    if m.required_slots["duration"] is None:
        assistant("And the **duration**? (e.g., *90 minutes*, *1h 30m*)", stage_hint=True)
        return

    # All slots known → propose + set awaiting_confirmation
    # Re-parse normalized values from filled slots to build Proposal
    d, start_t, end_t, _ = normalize_times(m.filled_slots["time_date"], now_tz())
    dur_min = int(m.filled_slots["duration"]) if m.filled_slots["duration"].isdigit() else parse_duration(m.filled_slots["duration"])
    if not (d and start_t and end_t and dur_min):
        assistant("I couldn't fully parse those details. Please try like: **study, tomorrow 19:00-21:00, 120 minutes**.", stage_hint=True)
        return

    proposal = Proposal(
        title=m.filled_slots["title"],
        date=d,
        start=start_t,
        end=end_t,
        duration_min=dur_min
    )
    st.session_state.model.last_proposal = proposal
    st.session_state.model.awaiting_confirmation = True
    assistant(f"{proposal.title}, {proposal.date.strftime('%b %d')} {proposal.start.strftime('%H:%M')}-{proposal.end.strftime('%H:%M')}. **Save this?**", stage_hint=True)

def handle_plan_edit(user_text: str):
    # Simple edit handlers: move/delete/rename/extend/shorten
    # 1) identify target by title fragment
    # 2) parse new time or action
    t = user_text.lower()
    # delete
    if "delete" in t or "cancel" in t:
        # try to find a title word after 'delete'
        frag = extract_title_guess(user_text) or ""
        matches = find_items_by_title_fragment(frag) if frag else []
        if not matches:
            assistant("Which item should I delete? Tell me a few words from its title.", stage_hint=True)
            return
        if len(matches) > 1:
            assistant(f"I found multiple matches: {', '.join([m['title'] for m in matches])}. Which one?", stage_hint=True)
            return
        # delete single
        st.session_state.agenda = [x for x in st.session_state.agenda if x["id"] != matches[0]["id"]]
        assistant(f"Deleted **{matches[0]['title']}**. What else can I help you with?")
        st.session_state.model.stage = None
        return

    # move/reschedule/change time
    if any(k in t for k in ["move","reschedule","change","shift","delay"]):
        # detect target + new time
        frag = extract_title_guess(user_text) or ""
        matches = find_items_by_title_fragment(frag) if frag else []
        if not matches:
            assistant("Which item should I move? Share a keyword from its title.", stage_hint=True)
            return
        if len(matches) > 1:
            assistant(f"I found multiple matches: {', '.join([m['title'] for m in matches])}. Which one?", stage_hint=True)
            return
        target = matches[0]
        # parse new when
        d, start_t, end_t, dur = normalize_times(user_text, now_tz())
        if not (d and start_t and end_t):
            assistant("Where should I move it? Say like: *tomorrow 7-8am* or *Fri 14:00-15:00*.", stage_hint=True)
            return
        target["date"] = d.isoformat()
        target["start"] = start_t.strftime("%H:%M")
        target["end"] = end_t.strftime("%H:%M")
        if dur: target["duration_min"] = dur
        assistant(f"Updated **{target['title']}** → {d.strftime('%a, %b %d')} {target['start']}-{target['end']}.")
        st.session_state.model.stage = None
        return

    # rename
    if "rename" in t:
        m = re.search(r'rename\s+(.+?)\s+to\s+(.+)$', user_text, re.I)
        if not m:
            assistant("Tell me: **rename [old words] to [new title]**.", stage_hint=True)
            return
        old_frag, new_title = m.group(1).strip(), m.group(2).strip()
        matches = find_items_by_title_fragment(old_frag)
        if not matches:
            assistant("I couldn't find that item to rename. Try a different keyword.", stage_hint=True)
            return
        if len(matches) > 1:
            assistant(f"Multiple matches: {', '.join([m['title'] for m in matches])}. Which one?", stage_hint=True)
            return
        matches[0]["title"] = new_title
        assistant(f"Renamed to **{new_title}**.")
        st.session_state.model.stage = None
        return

    assistant("Tell me what to edit. For example: *move workout to tomorrow 7:00-8:00*, *delete the 3pm call*, or *rename study to Calculus*.", stage_hint=True)

def handle_plan_check(user_text: str):
    t = user_text.lower()
    if "tomorrow" in t:
        present_agenda("tomorrow")
    elif "week" in t:
        present_agenda("week")
    else:
        present_agenda("today")
    # Offer quick actions
    st.markdown("Quick actions: try <span class='kbd'>move …</span>, <span class='kbd'>delete …</span>, or <span class='kbd'>mark done</span> with the buttons.", unsafe_allow_html=True)
    st.session_state.model.stage = None

def handle_other(user_text: str):
    t = user_text.lower()
    if "rule" in t or "role" in t or "policy" in t:
        assistant("I'm TimeBuddy—your friendly scheduling partner. I help you create, edit, and check time blocks with minimal friction.")
        st.session_state.model.stage = None
        return
    if "help" in t:
        assistant(
            "Try:\n"
            "- **Create**: *add study 7-9 tonight*, *plan my week*, *make a morning routine*\n"
            "- **Edit**: *move workout to tomorrow 7am*, *delete the 3pm call*\n"
            "- **Check**: *what's my day look like?*, *show this week*\n"
            "I’ll ask only for what’s missing (title, time/date, duration), then confirm before saving."
        )
        st.session_state.model.stage = None
        return
    if "timezone" in t:
        assistant(f"Current timezone: **{st.session_state.tz_str}**. Change it from the sidebar → Settings.")
        st.session_state.model.stage = None
        return
    assistant("I mainly handle planning, editing, and checking your schedule. Try something like: *add study 7-9 tonight (90 minutes)*.")
    st.session_state.model.stage = None


# ----------------------------
# Chat helpers
# ----------------------------
def assistant(text: str, stage_hint: bool = False):
    st.session_state.messages.append({"role":"assistant", "content": text, "hint": stage_hint})

def user(text: str):
    st.session_state.messages.append({"role":"user", "content": text})


# ----------------------------
# Sidebar (Settings / Identity / Shortcuts)
# ----------------------------
with st.sidebar:
    st.header("🕑 TimeBuddy")
    st.caption("Fast, friendly time blocking—built for low-friction planning.")
    st.markdown(f"<span class='badge'>Role</span> {ROLE}", unsafe_allow_html=True)
    st.write("")
    with st.expander("Goal"):
        st.write(GOAL)

    st.divider()
    st.subheader("Settings")
    tz = st.selectbox("Timezone", ["America/Los_Angeles","America/New_York","UTC","Asia/Seoul","Europe/Zurich"], index=0)
    if tz != st.session_state.tz_str:
        st.session_state.tz_str = tz
        st.success(f"Timezone set to {tz}")

    st.divider()
    st.subheader("Quick views")
    if st.button("Show Today"):
        present_agenda("today")
    if st.button("Show This Week"):
        present_agenda("week")

    st.divider()
    st.subheader("Tips")
    st.markdown(
        "- Create: `add study 7-9 tonight (120 minutes)`\n"
        "- Edit: `move study to Friday 08:00-09:30`\n"
        "- Delete: `delete study`\n"
        "- Rename: `rename study to Calculus`\n"
        "- Check: `what's my day look like?`"
    )


# ----------------------------
# Main Chat Area
# ----------------------------
st.title("TimeBuddy")
st.caption(f"Timezone: **{st.session_state.tz_str}** • {now_tz().strftime('%a, %b %d')}")

# Render history
for msg in st.session_state.messages:
    with st.chat_message("assistant" if msg["role"]=="assistant" else "user"):
        st.markdown(msg["content"])

# Chat input
prompt = st.chat_input("Tell me what you'd like to plan, edit, or check…")
if prompt:
    user(prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    # Slot filling for PLAN_CREATE if we're already in that stage
    m = st.session_state.model
    if m.awaiting_confirmation:
        handle_confirmation(prompt)
    elif m.stage == "PLAN_CREATE" and (m.required_slots["title"] is None or m.required_slots["time_date"] is None or m.required_slots["duration"] is None):
        # Fill the next missing slot with user input
        if m.required_slots["title"] is None:
            m.required_slots["title"] = prompt.strip()
            m.filled_slots["title"] = m.required_slots["title"]
            handle_plan_create(prompt, stay_in_stage=True)
        elif m.required_slots["time_date"] is None:
            m.required_slots["time_date"] = prompt.strip()
            m.filled_slots["time_date"] = m.required_slots["time_date"]
            handle_plan_create(prompt, stay_in_stage=True)
        elif m.required_slots["duration"] is None:
            m.required_slots["duration"] = prompt.strip()
            m.filled_slots["duration"] = m.required_slots["duration"]
            handle_plan_create(prompt, stay_in_stage=True)
    else:
        # Fresh routing
        route_to_stage(prompt)

    # Render assistant’s latest messages
    for msg in st.session_state.messages[::-1]:
        if msg["role"] == "assistant":
            with st.chat_message("assistant"):
                st.markdown(msg["content"])
            break  # only render the latest assistant message here


# ----------------------------
# Footer
# ----------------------------
st.write("")
st.caption("Pro tip: You can say *“add study 7–9 tonight (120 minutes)”* and I’ll take care of the rest.")
