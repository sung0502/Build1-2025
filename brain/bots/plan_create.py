# brain/bots/plan_create.py
"""
Create Bot: Handles PLAN_CREATE stage.
Extracts task details and asks for confirmation.
"""
from datetime import datetime
from core.contracts import BotRequest, BotEnvelope
from core.llm import LLM
from core.timeparse import parse_create_minimum
from core.state import calculate_end_time, detect_time_conflicts
from core.recurrence import detect_recurring_pattern, expand_recurring_pattern, format_recurring_dates


class CreateBot:
    """Bot for creating new tasks/schedules."""
    
    def __init__(self, llm: LLM, identity_path: str = "identities/creator.txt"):
        """
        Initialize create bot.
        
        Args:
            llm: LLM instance
            identity_path: Path to creator identity file
        """
        self.llm = llm
        self.identity = self._load_identity(identity_path)
    
    def _load_identity(self, path: str) -> str:
        """Load creator identity from file."""
        try:
            with open(path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            return "Extract task details: title, date, start_time, duration. Ask for confirmation."
    
    def run(self, request: BotRequest) -> BotEnvelope:
        """
        Process create request.

        Args:
            request: BotRequest with user input

        Returns:
            BotEnvelope with proposal and confirmation prompt
        """
        # Check for recurring pattern first
        pattern_info = detect_recurring_pattern(request.user_text)

        if pattern_info:
            return self._handle_recurring_task(request, pattern_info)
        else:
            return self._handle_single_task(request)

    def _handle_single_task(self, request: BotRequest) -> BotEnvelope:
        """Handle creation of a single (non-recurring) task."""
        # Parse task details
        title, date_str, start_time, duration = parse_create_minimum(
            request.user_text,
            request.now_iso_as_dt.date()
        )

        # Calculate end_time using overflow-safe function
        end_time = calculate_end_time(start_time, duration)

        # Build proposal
        proposal = {
            'title': title,
            'date': date_str,
            'start_time': start_time,
            'end_time': end_time,
            'duration': duration,
            'is_recurring': False
        }

        # Check for conflicts
        conflicts = detect_time_conflicts(request.schedules_snapshot, proposal)

        # Build confirmation message
        date_obj = datetime.fromisoformat(date_str).date()
        friendly_date = date_obj.strftime("%A, %B %d, %Y")  # "Monday, October 21, 2025"

        confirmation_msg = f"I'll add **{title}** on {friendly_date} from {start_time} to {end_time} ({duration} minutes). Save this?"

        # Add conflict warning if needed
        if conflicts:
            conflict_names = ", ".join([f"**{c['title']}**" for c in conflicts[:2]])
            if len(conflicts) > 2:
                conflict_names += f" and {len(conflicts) - 2} more"
            confirmation_msg = f"⚠️ **Time conflict detected!** This overlaps with: {conflict_names}\n\n{confirmation_msg}"

        return BotEnvelope(
            stage="PLAN_CREATE",
            create=proposal,
            user_facing=confirmation_msg,
            ask_confirmation=True,
            proposal=proposal
        )

    def _handle_recurring_task(self, request: BotRequest, pattern_info: dict) -> BotEnvelope:
        """Handle creation of recurring tasks."""
        # Parse base task details
        title, date_str, start_time, duration = parse_create_minimum(
            request.user_text,
            request.now_iso_as_dt.date()
        )

        # Calculate end_time
        end_time = calculate_end_time(start_time, duration)

        # Check if timeframe is specified
        if not pattern_info.get('timeframe'):
            # Ask for clarification
            pattern_desc = self._describe_pattern(pattern_info)
            return BotEnvelope(
                stage="PLAN_CREATE",
                user_facing=f"I'll create **{title}** {pattern_desc}. For how long should this repeat? (e.g., 'for this month', 'for 4 weeks', 'until Nov 30')",
                ask_confirmation=False
            )

        # Expand recurring pattern into individual tasks
        tasks, recurrence_id, timeframe_desc = expand_recurring_pattern(
            pattern_info,
            title,
            start_time,
            duration,
            end_time,
            request.now_iso_as_dt.date(),
            max_occurrences=30
        )

        if not tasks:
            return BotEnvelope(
                stage="PLAN_CREATE",
                user_facing=f"I couldn't find any matching dates for that pattern. Can you try rephrasing?",
                ask_confirmation=False
            )

        # Check ALL tasks for conflicts
        all_conflicts = []
        for task in tasks:
            conflicts = detect_time_conflicts(request.schedules_snapshot, task)
            if conflicts:
                all_conflicts.append({
                    'date': task['date'],
                    'conflicts': conflicts
                })

        # Build confirmation message
        task_count = len(tasks)
        dates_list = [datetime.fromisoformat(t['date']).date() for t in tasks]
        dates_formatted = format_recurring_dates(dates_list, max_show=4)

        pattern_desc = self._describe_pattern(pattern_info)

        confirmation_msg = f"I'll add **{title}** {pattern_desc} on {task_count} dates ({dates_formatted}) from {start_time} to {end_time} ({duration} minutes)."

        # Add conflict warnings
        if all_conflicts:
            conflict_count = len(all_conflicts)
            conflict_details = []
            for conflict_info in all_conflicts[:2]:  # Show first 2
                date_obj = datetime.fromisoformat(conflict_info['date']).date()
                date_str_short = date_obj.strftime('%b %d')
                task_names = ", ".join([c['title'] for c in conflict_info['conflicts'][:2]])
                conflict_details.append(f"{date_str_short} (overlaps with {task_names})")

            conflict_text = "; ".join(conflict_details)
            if conflict_count > 2:
                conflict_text += f" and {conflict_count - 2} more dates"

            confirmation_msg += f"\n\n⚠️ **{conflict_count} conflicts detected:** {conflict_text}"

        confirmation_msg += f"\n\nCreate all {task_count} tasks?"

        # Build proposal
        proposal = {
            'is_recurring': True,
            'tasks': tasks,
            'recurrence_id': recurrence_id,
            'pattern_info': pattern_info
        }

        return BotEnvelope(
            stage="PLAN_CREATE",
            create=proposal,
            user_facing=confirmation_msg,
            ask_confirmation=True,
            proposal=proposal
        )

    def _describe_pattern(self, pattern_info: dict) -> str:
        """Generate human-readable description of recurrence pattern."""
        pattern_type = pattern_info.get('pattern_type')

        if pattern_type == 'daily':
            return "every day"
        elif pattern_type == 'weekdays':
            return "every weekday"
        elif pattern_type == 'specific_days':
            day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            days = pattern_info.get('days', [])
            day_name_list = [day_names[d] for d in days]
            if len(day_name_list) == 1:
                return f"every {day_name_list[0]}"
            else:
                return f"every {', '.join(day_name_list)}"
        else:
            return "recurring"
