# app.py
# Streamlit UI for "TimeBuddy" with stage routing, slot-filling, confirmations, and an in-memory agenda.

from __future__ import annotations
import re
import uuid
from datetime import datetime, timedelta, date, time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd  # optional; kept for future export features
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
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
.badge { display:inline-block; padding:2px 8px; border-radius:12px; font-size:0.75rem; font-weight:600;
  background:#EEF2FF; color:#3730A3; border:1px solid #C7D2FE; }
.rule-note { font-size:0.85rem; color:#4B5563; }
.small { font-size:0.85rem; color:#6B7280; }
.agenda-card { border:1px solid #E5E7EB; border-radius:12px; padding:12px; margin-bottom:10px; background:#FFFFFF;
  box-shadow: 0 1px 1px rgba(0,0,0,0.02); }
.agenda-title { font-weight:600; }
.kbd { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
       background:#F3F4F6; border:1px solid #E5E7EB; border-radius:6px; padding:2px 6px; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ----------------------------
# Identity (sidebar summary)
# ----------------------------
ROLE = (
    "You are TimeBuddy, a personal assistant created by Sung Park. "
    "You reduce friction in time management by automating planning, editing, and checking schedules."
)
GOAL = (
    "Help users save and load schedules and follow through. Learn habits to suggest better time blocks."
)

TRIGGERS = {
    "PLAN_CREATE": ["add","plan","schedule","set","block","create","make","remind","reminder","start","new","routine"],
    "PLAN_EDIT":   ["move","reschedule","change","shift","delay","extend","shorten","rename","delete","cancel"],
    "PLAN_CHECK":  ["show","what's","whats","view","list","agenda","calendar","due","status","done","today","tomorrow","week"],
    "OTHER":       ["help","settings","timezone","role","rules","policy","how you work","chit","chat"]
}

YES_PATTERNS = {"yes","y","yeah","yep","sure","ok","okay","confirm","do it","save","✅","👍"}
NO_PATTERNS  = {"no","n","nope","cancel","don’t","dont","stop","not now","❌"}

# ----------------------------
# State Model
# ----------------------------
@dataclass
class PendingOperation:
    type: Optional[str] = None  # "create" | "delete" | None
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
    required_slots: Dict[str, Optional[str]] = field(
        default_factory=lambda: {"title": None, "time_date": None, "duration": None}
    )
    filled_slots: Dict[str, Optional[str]] = field(
        default_factory=lambda: {"title": None, "time_date": None, "duration": None}
    )
    # Edit context (for multi-turn PLAN_EDIT)
    edit_target_id: Optional[str] = None
    edit_time_text: Optional[str] = None

    pending_operation: PendingOperation = field(default_factory=PendingOperation)
    awaiting_confirmation: bool = False
    last_proposal: Optional[Proposal] = None
    confidence: float = 1.0

# ----------------------------
# Session init
# ----------------------------
def init_session():
    if "tz_str" not in st.session_state:
        st.session_state.tz_str = PRIMARY_TZ
    if "model" not in st.session_state:
        st.session_state.model = StateModel()
    if "agenda" not in st.session_state:
        st.session_state.agenda: List[Dict[str, Any]] = []
    if "messages" not in st.session_state:
        st.session_state.messages: List[Dict[str, Any]] = []

init_session()

def now_tz() -> datetime:
    return datetime.now(ZoneInfo(st.session_state.tz_str))

def parse_yes_no(txt: str) -> Optional[bool]:
    t = txt.strip().lower()
    if t in YES_PATTERNS: return True
    if t in NO_PATTERNS: return False
    return None

# ----------------------------
# Time parsing helpers
# ----------------------------
WEEKDAYS = {
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
    if "today" in t or "tonight" in t: return base_dt.date()
    if "tomorrow" in t or "tmr" in t or "tmrw" in t: return (base_dt + timedelta(days=1)).date()
    for wd_str, wd_idx in WEEKDAYS.items():
        if re.search(rf"\b{wd_str}\b", t):
            return next_weekday(base_dt.date(), wd_idx) if base_dt.date().weekday()!=wd_idx else base_dt.date()
    try:
        dt = du_parser.parse(text, fuzzy=True, default=base_dt)
        return dt.date()
    except Exception:
        return base_dt.date()

def parse_time_range(text: str) -> Optional[Tuple[time, time]]:
    """
    Robustly parse ranges like 7-9, 7pm-9pm, 7-9pm, 07:00-09:00.
    Ignores date-like hyphens (YYYY-MM-DD) by scanning all pairs and picking the last valid match.
    """
    t = text.lower().replace("—","-").replace("–","-").replace(" to ","-")
    pattern = r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*-\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?'
    matches = list(re.finditer(pattern, t))
    if not matches: return None

    def to_24h(h, mm, ap):
        if ap == "am":
            if h == 12: h = 0
        elif ap == "pm":
            if h != 12: h += 12
        return time(hour=h, minute=mm)

    for m in reversed(matches):
        h1, m1, ap1, h2, m2, ap2 = m.groups()
        h1, h2 = int(h1), int(h2)
        m1 = int(m1) if m1 else 0
        m2 = int(m2) if m2 else 0

        # Copy AM/PM if only one side has it, e.g. "7-9pm"
        if (ap1 is None) and (ap2 in ("am","pm")): ap1 = ap2
        if (ap2 is None) and (ap1 in ("am","pm")): ap2 = ap1

        try:
            if ap1 or ap2:
                t1 = to_24h(h1, m1, ap1)
                t2 = to_24h(h2, m2, ap2)
            else:
                if not (0 <= h1 <= 23 and 0 <= m1 <= 59 and 0 <= h2 <= 23 and 0 <= m2 <= 59):
                    continue
                t1 = time(hour=h1, minute=m1)
                t2 = time(hour=h2, minute=m2)
            return t1, t2
        except ValueError:
            continue
    return None

def parse_single_time(text: str) -> Optional[time]:
    """Parse a single time like '8am', '08:30', '8', '8 am'."""
    t = text.lower()
    m = re.search(r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b', t)
    if not m: return None
    hh = int(m.group(1))
    mm = int(m.group(2)) if m.group(2) else 0
    ap = m.group(3)
    if ap:
        if ap == "am":
            if hh == 12: hh = 0
        elif ap == "pm":
            if hh != 12: hh += 12
        return time(hh, mm)
    # 24h fallback
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return time(hh, mm)
    return None

def parse_duration(text: str) -> Optional[int]:
    """
    Returns minutes. Accepts:
      - "for 90 minutes", "90 minutes", "1h 30m", "2 hours"
      - "an hour", "about an hour", "like an hour"
      - "half an hour" (30), "1.5 hours" (90), "2 and a half hours" (150)
    """
    t = text.lower()
    # soften fillers
    t = re.sub(r'\b(about|around|roughly|like|approximately|approx\.?)\b\s*', '', t)

    # Half/quarter hour phrases
    if re.search(r'\bhalf\s+an?\s+hour\b', t): return 30
    if re.search(r'\bquarter\s+of\s+an?\s+hour\b', t) or re.search(r'\bquarter\s+hour\b', t): return 15
    if re.search(r'\b(an|a)\s+hour\s+and\s+a?\s+half\b', t): return 90
    if re.search(r'\b(an|a)\s+hour\b', t): return 60  # after the 90-min case

    # "X and a half hours"
    m = re.search(r'\b(\d+)\s+and\s+a?\s+half\s*(h|hour|hours)\b', t)
    if m:
        return int(m.group(1)) * 60 + 30

    # Decimal hours like 1.5 hours
    m = re.search(r'\b(\d+(?:\.\d+)?)\s*(h|hour|hours)\b', t)
    if m:
        return int(round(float(m.group(1)) * 60))

    # Hours + optional minutes: "2 hours 30 (m|min|minutes)"
    m = re.search(r'(\d+)\s*(h|hour|hours)\s*(\d+)?\s*(m|min|mins|minutes)?', t)
    if m:
        h = int(m.group(1)); m2 = int(m.group(3)) if m.group(3) else 0
        return h*60 + m2

    # Minutes only
    m = re.search(r'\b(\d+)\s*(m|min|mins|minutes)\b', t)
    if m:
        return int(m.group(1))

    # "for X min/hour"
    m = re.search(r'for\s+(\d+)\s*(m|min|mins|minutes)\b', t)
    if m:
        return int(m.group(1))
    m = re.search(r'for\s+(\d+)\s*(h|hour|hours)\b', t)
    if m:
        return int(m.group(1)) * 60

    return None

def normalize_times(text: str, base_dt: datetime) -> Tuple[Optional[date], Optional[time], Optional[time], Optional[int]]:
    """
    Tries to extract date, start, end, duration. Supports:
      - Full ranges in text (e.g., "tomorrow 7-9pm")
      - Single start time (e.g., "tomorrow 8am") -> start only; end requires duration elsewhere
      - When text begins with ISO date, strip it for time parsing
    """
    # If string starts with ISO date "YYYY-MM-DD ...", keep full for date, strip for time
    iso_match = re.match(r'^\s*(\d{4}-\d{2}-\d{2})\s+(.*)$', text.strip())
    time_text = iso_match.group(2) if iso_match else text

    d = infer_date(text, base_dt)  # still use full original text for the date
    rng = parse_time_range(time_text)
    if rng:
        start_t, end_t = rng
    else:
        start_t = parse_single_time(time_text)
        end_t = None
    dur = parse_duration(text)
    if rng and not dur:
        # compute duration from range
        start_dt = datetime.combine(d, start_t)
        end_dt = datetime.combine(d, end_t)
        if end_dt <= start_dt: end_dt += timedelta(days=1)
        dur = int((end_dt - start_dt).total_seconds() // 60)
    return d, start_t, end_t, dur

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
    frag = fragment.lower().strip()
    if not frag: return []
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
    else:
        start = tznow.date()
        end = start + timedelta(days=6)
        items = [it for it in st.session_state.agenda if start <= du_parser.parse(it["date"]).date() <= end]
        label = f"This Week ({start.strftime('%b %d')} – {end.strftime('%b %d')})"

    st.markdown(f"**{label}**")
    if not items:
        st.write("No items yet.")
        return

    items_sorted = sorted(items, key=lambda x: (x["date"], x["start"]))
    for it in items_sorted:
        st.markdown(
            f"<div class='agenda-card'>"
            f"<div class='agenda-title'>{it['title']}</div>"
            f"<div class='small'>{du_parser.parse(it['date']).strftime('%a, %b %d')} • {it['start']}–{it['end']} • {it['duration_min']} min</div>"
            f"<div class='small'>Status: {'✅ Done' if it['done'] else '⏳ Pending'}</div>"
            f"</div>",
            unsafe_allow_html=True
        )
        # NOTE: Buttons removed per request

# ----------------------------
# Chat helpers
# ----------------------------
def assistant(text: str, stage_hint: bool = False):
    st.session_state.messages.append({"role":"assistant", "content": text, "hint": stage_hint})

def user_msg(text: str):
    st.session_state.messages.append({"role":"user", "content": text})

# ----------------------------
# Confirmation handler (create + delete)
# ----------------------------
def handle_confirmation(user_text: str):
    m = st.session_state.model
    yn = parse_yes_no(user_text)
    if yn is None:
        assistant("Please reply with **yes** to confirm or **no** to cancel.", stage_hint=True)
        return

    # Delete confirmation
    if m.pending_operation.type == "delete" and m.pending_operation.target_id:
        if yn is True:
            tid = m.pending_operation.target_id
            to_delete = next((x for x in st.session_state.agenda if x["id"] == tid), None)
            if to_delete:
                st.session_state.agenda = [x for x in st.session_state.agenda if x["id"] != tid]
                assistant(f"Deleted **{to_delete['title']}** on {to_delete['date']} {to_delete['start']}-{to_delete['end']}.")
            else:
                assistant("That item was not found (maybe already deleted).")
        else:
            assistant("Okay, I won’t delete that.")
        st.session_state.model = StateModel()  # full reset
        return

    # Create confirmation
    if m.last_proposal:
        if yn is True:
            save_agenda_item(m.last_proposal)
            assistant("Saved ✅\n\nOverview: " + format_overview(m.last_proposal) + "\n\nWhat else can I help you with?")
        else:
            assistant("Okay, I won’t save that.\n\nWhat would you like to do next?")
        st.session_state.model = StateModel()
        return

    # Fallback
    assistant("Nothing to confirm. What would you like to do next?")
    st.session_state.model = StateModel()

# ----------------------------
# Stage handlers
# ----------------------------
def handle_plan_create(user_text: str, stay_in_stage: bool = False):
    m = st.session_state.model

    # First attempt to parse from the message if it's the first turn in this stage
    if not stay_in_stage:
        d, start_t, end_t, dur = normalize_times(user_text, now_tz())
        if d and (start_t or end_t):
            # store raw, we'll reconcile later
            m.required_slots["time_date"] = user_text.strip()
            m.filled_slots["time_date"] = m.required_slots["time_date"]
        if dur:
            m.required_slots["duration"] = f"{dur}"
            m.filled_slots["duration"] = m.required_slots["duration"]
        title_guess = extract_title_guess_create(user_text)
        if title_guess and len(title_guess) >= 2:
            m.required_slots["title"] = title_guess
            m.filled_slots["title"] = title_guess

    # Ask for missing slots in order
    if m.required_slots["title"] is None:
        assistant("Got it—what’s the **title** of this block?", stage_hint=True); return
    if m.required_slots["time_date"] is None:
        assistant("Great. When should it happen? (e.g., *tomorrow 7-9pm*, *Fri 08:00*).", stage_hint=True); return
    if m.required_slots["duration"] is None:
        assistant("And the **duration**? (e.g., *90 minutes*, *1h 30m*, *an hour*).", stage_hint=True); return

    # All slots known → build a proposal (support start-only + duration)
    d, start_t, end_t, _ = normalize_times(m.filled_slots["time_date"], now_tz())
    dur_min = int(m.filled_slots["duration"]) if m.filled_slots["duration"].isdigit() else parse_duration(m.filled_slots["duration"])

    if not d:
        assistant("I couldn't parse the date. Try like: **tomorrow 19:00**.", stage_hint=True); return

    # If no end but we have start + duration, compute end
    if start_t and not end_t and dur_min:
        end_dt = (datetime.combine(d, start_t) + timedelta(minutes=dur_min)).time()
        end_t = end_dt

    if not (start_t and end_t and dur_min):
        assistant("I couldn't fully parse those details. Please try like: **study, tomorrow 19:00-21:00, 120 minutes**.", stage_hint=True); return

    proposal = Proposal(m.filled_slots["title"], d, start_t, end_t, dur_min)
    m.last_proposal = proposal
    m.pending_operation = PendingOperation(type="create")
    m.awaiting_confirmation = True
    assistant(f"{proposal.title}, {proposal.date.strftime('%b %d')} {proposal.start.strftime('%H:%M')}-{proposal.end.strftime('%H:%M')}. **Save this?**", stage_hint=True)

# Helper to extract title for CREATE (tolerant)
def extract_title_guess_create(text: str) -> Optional[str]:
    t = text
    # Remove common verbs
    t = re.sub(r'\b(add|plan|schedule|set|block|create|make|remind|reminder|start|new)\b', '', t, flags=re.I)
    # Remove prepositions commonly used in titles (keep content after them)
    t = re.sub(r'\b(to)\b', '', t, flags=re.I)
    # Remove edit verbs just in case
    t = re.sub(r'\b(move|reschedule|change|shift|delay|extend|shorten|rename|delete|cancel)\b', '', t, flags=re.I)
    # Remove date/time-like tokens
    t = re.sub(r'\b(today|tonight|tomorrow|tmr|this week|next week|mon(day)?|tue(s|sday)?|wed(nesday)?|thu(r|rs|rsday)?|fri(day)?|sat(urday)?|sun(day)?)\b', '', t, flags=re.I)
    t = re.sub(r'\d{4}-\d{2}-\d{2}', '', t)
    t = re.sub(r'\d{1,2}:\d{2}', '', t)
    t = re.sub(r'\d{1,2}\s*(am|pm)\b', '', t, flags=re.I)
    t = re.sub(r'\d{1,2}\s*[-–]\s*\d{1,2}', '', t)
    t = re.sub(r'for\s+\d+(\s*(min|mins|minutes|h|hour|hours))?', '', t, flags=re.I)
    # Clean and trim
    t = re.sub(r'\s+', ' ', t).strip(' ,.-')
    return t if t else None

def handle_plan_edit(user_text: str):
    m = st.session_state.model
    t = user_text.lower()

    # 1) DELETE with confirmation
    if "delete" in t or "cancel" in t:
        frag = extract_title_guess_edit_target(user_text) or ""
        matches = find_items_by_title_fragment(frag) if frag else []
        if not matches:
            assistant("Which item should I delete? Tell me a few words from its title.", stage_hint=True); return
        if len(matches) > 1:
            assistant(f"I found multiple matches: {', '.join([m['title'] for m in matches])}. Which one?", stage_hint=True); return
        target = matches[0]
        m.pending_operation = PendingOperation(type="delete", target_id=target["id"])
        m.awaiting_confirmation = True
        assistant(f"Delete **{target['title']}** on {target['date']} {target['start']}-{target['end']}? (**yes**/**no**)", stage_hint=True)
        return

    # 2) MOVE / RESCHEDULE
    if any(k in t for k in ["move","reschedule","change","shift","delay"]):
        # Try to parse "move X to Y"
        mobj = re.search(r'\bmove\s+(.+?)\s+(?:to|->)\s+(.+)$', user_text, re.I)
        if mobj:
            frag = mobj.group(1).strip()
            m.edit_time_text = mobj.group(2).strip()
        else:
            frag = extract_title_guess_edit_target(user_text) or frag_from_single_word(user_text)

        if m.edit_target_id is None:
            matches = find_items_by_title_fragment(frag) if frag else []
            if not matches:
                assistant("Which item should I move? Share a keyword from its title.", stage_hint=True); return
            if len(matches) > 1:
                assistant(f"I found multiple matches: {', '.join([x['title'] for x in matches])}. Which one?", stage_hint=True); return
            m.edit_target_id = matches[0]["id"]

        # If we don't yet have the time, try to extract from this message; else ask
        if not m.edit_time_text:
            # extract any time phrase from message; if none, ask for it
            tm_rng = parse_time_range(user_text)
            if tm_rng or parse_single_time(user_text) or any(w in t for w in ["today","tomorrow","mon","tue","wed","thu","fri","sat","sun","week"]):
                m.edit_time_text = user_text
            else:
                assistant("When should I move it to? (e.g., *tomorrow 10-11*, *Fri 14:00-15:00*)", stage_hint=True); return

        # Apply move
        target = next((x for x in st.session_state.agenda if x["id"] == m.edit_target_id), None)
        if not target:
            assistant("I couldn't find that item anymore. Try again.", stage_hint=True); st.session_state.model = StateModel(); return

        d, start_t, end_t, dur = normalize_times(m.edit_time_text, now_tz())
        if not (d and (start_t and end_t or (start_t and dur))):
            assistant("I couldn't parse the new time. Try like: *tomorrow 10-11*.", stage_hint=True); return

        if start_t and not end_t and dur:
            end_dt = (datetime.combine(d, start_t) + timedelta(minutes=dur)).time()
            end_t = end_dt

        target["date"] = d.isoformat()
        target["start"] = start_t.strftime("%H:%M")
        target["end"] = end_t.strftime("%H:%M")
        if dur: target["duration_min"] = dur

        assistant(f"Updated **{target['title']}** → {d.strftime('%a, %b %d')} {target['start']}-{target['end']}.")
        st.session_state.model = StateModel()  # clear ctx
        return

    # 3) RENAME
    if "rename" in t:
        mobj = re.search(r'rename\s+(.+?)\s+to\s+(.+)$', user_text, re.I)
        if not mobj:
            assistant("Tell me: **rename [old words] to [new title]**.", stage_hint=True); return
        old_frag, new_title = mobj.group(1).strip(), mobj.group(2).strip()
        matches = find_items_by_title_fragment(old_frag)
        if not matches: assistant("I couldn't find that item to rename. Try a different keyword.", stage_hint=True); return
        if len(matches) > 1: assistant(f"Multiple matches: {', '.join([x['title'] for x in matches])}. Which one?", stage_hint=True); return
        matches[0]["title"] = new_title
        assistant(f"Renamed to **{new_title}**."); st.session_state.model = StateModel(); return

    # Default help within edit
    assistant("Tell me what to edit. For example: *move workout to tomorrow 7:00-8:00*, *delete study*, or *rename study to Calculus*.", stage_hint=True)

def extract_title_guess_edit_target(text: str) -> Optional[str]:
    # Focus on grabbing words after edit verbs and before "to ..."
    m = re.search(r'(?:move|reschedule|change|shift|delay|delete|cancel)\s+(.+?)(?:\s+(?:to|->)\s+.+)?$', text, re.I)
    if m:
        frag = m.group(1)
    else:
        frag = text
    # strip common time/date tokens
    frag = re.sub(r'\b(today|tonight|tomorrow|tmr|this week|next week|mon(day)?|tue(s|sday)?|wed(nesday)?|thu(r|rs|rsday)?|fri(day)?|sat(urday)?|sun(day)?)\b', '', frag, flags=re.I)
    frag = re.sub(r'\d{4}-\d{2}-\d{2}', '', frag)
    frag = re.sub(r'\d{1,2}:\d{2}', '', frag)
    frag = re.sub(r'\d{1,2}\s*(am|pm)\b', '', frag, flags=re.I)
    frag = re.sub(r'\d{1,2}\s*[-–]\s*\d{1,2}', '', frag)
    frag = re.sub(r'\s+', ' ', frag).strip(' ,.-')
    return frag if frag else None

def frag_from_single_word(text: str) -> Optional[str]:
    # When user replies just "study"
    t = text.strip()
    if 1 <= len(t) <= 50:
        return t
    return None

def handle_plan_check(user_text: str):
    t = user_text.lower()
    if "tomorrow" in t: present_agenda("tomorrow")
    elif "week" in t: present_agenda("week")
    else: present_agenda("today")
    st.markdown("Quick actions: try <span class='kbd'>move …</span>, <span class='kbd'>delete …</span>, or ask me to rename.", unsafe_allow_html=True)
    st.session_state.model.stage = None

def handle_other(user_text: str):
    t = user_text.lower()
    if "rule" in t or "role" in t or "policy" in t:
        assistant("I'm TimeBuddy—your friendly scheduling partner. I help you create, edit, and check time blocks with minimal friction.")
    elif "help" in t:
        assistant("Try:\n- **Create**: *add study 7-9 tonight*, *plan my week*\n- **Edit**: *move workout to tomorrow 7am*, *delete the 3pm call*\n- **Check**: *what's my day look like?*, *show this week*\nI’ll ask only for what’s missing (title, time/date, duration), then confirm before saving.")
    elif "timezone" in t:
        assistant(f"Current timezone: **{st.session_state.tz_str}**. Change it from the sidebar → Settings.")
    else:
        assistant("I mainly handle planning, editing, and checking your schedule. Try something like: *add study tomorrow 8am (an hour)*.")
    st.session_state.model.stage = None

# ----------------------------
# Router
# ----------------------------
def classify_stage(user_text: str) -> Tuple[str, float]:
    t = user_text.lower()
    score = {"PLAN_CREATE":0,"PLAN_EDIT":0,"PLAN_CHECK":0,"OTHER":0}
    for stage, words in TRIGGERS.items():
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", t):
                score[stage] += 1
    stage = max(score, key=score.get)
    confidence = min(1.0, 0.4 + 0.2*score[stage])
    if all(v==0 for v in score.values()):
        if re.search(r'\btoday|tomorrow|week\b', t):
            stage, confidence = "PLAN_CHECK", 0.65
        else:
            stage, confidence = "PLAN_CREATE", 0.55
    return stage, confidence

def route_to_stage(user_text: str):
    m = st.session_state.model
    if m.awaiting_confirmation:
        handle_confirmation(user_text); return

    # Stay in multi-turn stages
    if m.stage == "PLAN_CREATE" and (m.required_slots["title"] is None or m.required_slots["time_date"] is None or m.required_slots["duration"] is None):
        handle_plan_create(user_text, stay_in_stage=True); return
    if m.stage == "PLAN_EDIT":
        handle_plan_edit(user_text); return

    # Otherwise classify fresh
    stage, conf = classify_stage(user_text)
    m.stage = stage
    m.confidence = conf
    assistant(f"Entering **{stage}** stage.", stage_hint=True)

    if conf < 0.6:
        if stage == "PLAN_CREATE":
            assistant("I think you're trying to schedule something. Could you share the **title**, **time/date**, and **duration**?", stage_hint=True)
        elif stage == "PLAN_EDIT":
            assistant("Tell me what to change (e.g., *move study to tomorrow 10-11*).", stage_hint=True)
        elif stage == "PLAN_CHECK":
            assistant("Do you want **today**, **tomorrow**, or **this week**?", stage_hint=True)
        else:
            handle_other(user_text)
        return

    if stage == "PLAN_CREATE": handle_plan_create(user_text)
    elif stage == "PLAN_EDIT": handle_plan_edit(user_text)
    elif stage == "PLAN_CHECK": handle_plan_check(user_text)
    else: handle_other(user_text)

# ----------------------------
# Sidebar
# ----------------------------
with st.sidebar:
    st.header("🕑 TimeBuddy")
    st.caption("Fast, friendly time blocking—built for low-friction planning.")
    st.markdown(f"<span class='badge'>Role</span> {ROLE}", unsafe_allow_html=True)
    with st.expander("Goal"): st.write(GOAL)

    st.divider()
    st.subheader("Settings")
    tz = st.selectbox("Timezone", ["America/Los_Angeles","America/New_York","UTC","Asia/Seoul","Europe/Zurich"], index=0)
    if tz != st.session_state.tz_str:
        st.session_state.tz_str = tz
        st.success(f"Timezone set to {tz}")

    st.divider()
    st.subheader("Quick views")
    if st.button("Show Today"): present_agenda("today")
    if st.button("Show This Week"): present_agenda("week")

    st.divider()
    st.subheader("Tips")
    st.markdown(
        "- Create: `add study tomorrow 8am (an hour)` or `add study 7-9 tonight`\n"
        "- Edit: `move study to Friday 08:00-09:30`\n"
        "- Delete: `delete study` (now asks to confirm)\n"
        "- Rename: `rename study to Calculus`\n"
        "- Check: `what's my day look like?`"
    )

# ----------------------------
# Main Chat UI
# ----------------------------
st.title("TimeBuddy")
st.caption(f"Timezone: **{st.session_state.tz_str}** • {now_tz().strftime('%a, %b %d')}")

# History
for msg in st.session_state.messages:
    with st.chat_message("assistant" if msg["role"]=="assistant" else "user"):
        st.markdown(msg["content"])

# Input
prompt = st.chat_input("Tell me what you'd like to plan, edit, or check…")
if prompt:
    user_msg(prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    m = st.session_state.model
    if m.awaiting_confirmation:
        handle_confirmation(prompt)
    elif m.stage == "PLAN_CREATE" and (m.required_slots["title"] is None or m.required_slots["time_date"] is None or m.required_slots["duration"] is None):
        # Fill the next missing slot directly with user's reply
        if m.required_slots["title"] is None:
            m.required_slots["title"] = prompt.strip(); m.filled_slots["title"] = m.required_slots["title"]
            handle_plan_create(prompt, stay_in_stage=True)
        elif m.required_slots["time_date"] is None:
            m.required_slots["time_date"] = prompt.strip(); m.filled_slots["time_date"] = m.required_slots["time_date"]
            handle_plan_create(prompt, stay_in_stage=True)
        elif m.required_slots["duration"] is None:
            m.required_slots["duration"] = prompt.strip(); m.filled_slots["duration"] = m.required_slots["duration"]
            handle_plan_create(prompt, stay_in_stage=True)
    else:
        route_to_stage(prompt)

    # Render latest assistant reply
    for msg in reversed(st.session_state.messages):
        if msg["role"] == "assistant":
            with st.chat_message("assistant"):
                st.markdown(msg["content"])
            break

st.write("")
st.caption("Pro tip: You can say *“add study tomorrow 8am (an hour)”* and I’ll take care of the rest.")
