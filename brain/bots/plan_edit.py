# brain/bots/plan_edit.py
"""
Edit Bot: Handles PLAN_EDIT stage.
Identifies target task and proposes changes.
"""
from datetime import timedelta
from typing import Optional
from core.contracts import BotRequest, BotEnvelope
from core.llm import LLM
from core.timeparse import parse_time_of_day, parse_duration_minutes, infer_date


class EditBot:
    """Bot for editing existing tasks/schedules."""
    
    def __init__(self, llm: LLM, identity_path: str = "identities/editor.txt"):
        """
        Initialize edit bot.
        
        Args:
            llm: LLM instance
            identity_path: Path to editor identity file
        """
        self.llm = llm
        self.identity = self._load_identity(identity_path)
    
    def _load_identity(self, path: str) -> str:
        """Load editor identity from file."""
        try:
            with open(path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            return "Identify the most relevant task and propose ONE change. Ask for confirmation."
    
    def run(self, request: BotRequest) -> BotEnvelope:
        """
        Process edit request.

        Args:
            request: BotRequest with user input

        Returns:
            BotEnvelope with edit proposal and confirmation prompt
        """
        if not request.schedules_snapshot:
            return BotEnvelope(
                stage="PLAN_EDIT",
                user_facing="You don't have any tasks yet. Would you like to create one?",
                ask_confirmation=False
            )

        # Check for bulk delete patterns first
        bulk_result = self._check_bulk_delete(request)
        if bulk_result:
            return bulk_result

        # Use LLM to identify target and changes
        schedules_text = "\n".join([
            f"- ID: {s['id']}, Title: {s['title']}, Date: {s['date']}, Time: {s['start_time']}, Type: {s['type']}"
            for s in request.schedules_snapshot[-10:]  # Last 10 for context
        ])

        prompt = f"""
User wants to edit a task. Here are their recent tasks:

{schedules_text}

User message: "{request.user_text}"

Identify the MOST relevant task and determine what change to make.
Common actions: move time, change date, rename, delete, mark complete, extend duration.

Respond with JSON containing ONE of these:
- Delete: {{"action": "delete", "id": "task_id"}}
- Complete: {{"action": "complete", "id": "task_id"}}
- Update: {{"action": "update", "id": "task_id", "changes": {{"start_time": "10:00"}}}}

Only include fields that should change.
"""

        try:
            result = self.llm.classify_json(
                system_instruction=self.identity,
                prompt=prompt,
                schema_hint='{"action": "delete|complete|update", "id": "...", "changes": {...}}'
            )
        except Exception as e:
            return BotEnvelope(
                stage="PLAN_EDIT",
                user_facing="😕 I'm having trouble processing your request. Please try again or be more specific about which task you want to edit.",
                ask_confirmation=False
            )

        if not result or 'id' not in result:
            return BotEnvelope(
                stage="PLAN_EDIT",
                user_facing="I couldn't identify which task you want to edit. Can you be more specific?",
                ask_confirmation=False
            )

        # Find the target task
        target_task = None
        for s in request.schedules_snapshot:
            if s['id'] == result['id']:
                target_task = s
                break

        if not target_task:
            return BotEnvelope(
                stage="PLAN_EDIT",
                user_facing="I couldn't find that task. Can you try again?",
                ask_confirmation=False
            )

        # Build confirmation message
        action = result.get('action')
        if action == 'delete':
            confirmation_msg = f"Delete **{target_task['title']}** on {target_task['date']}? Save this?"
            proposal = {'action': 'delete', 'id': target_task['id']}

        elif action == 'complete':
            confirmation_msg = f"Mark **{target_task['title']}** as complete? Save this?"
            proposal = {'action': 'complete', 'id': target_task['id']}

        else:  # update
            changes = result.get('changes', {})
            change_desc = []
            if 'start_time' in changes:
                change_desc.append(f"time to {changes['start_time']}")
            if 'date' in changes:
                change_desc.append(f"date to {changes['date']}")
            if 'title' in changes:
                change_desc.append(f"title to '{changes['title']}'")
            if 'duration' in changes:
                change_desc.append(f"duration to {changes['duration']} min")

            change_text = ", ".join(change_desc) if change_desc else "the task"
            confirmation_msg = f"Update **{target_task['title']}**: change {change_text}? Save this?"
            proposal = {'action': 'update', 'id': target_task['id'], 'changes': changes}

        return BotEnvelope(
            stage="PLAN_EDIT",
            edit=proposal,
            user_facing=confirmation_msg,
            ask_confirmation=True,
            proposal=proposal
        )

    def _check_bulk_delete(self, request: BotRequest) -> Optional[BotEnvelope]:
        """
        Check if user wants to delete multiple tasks and return appropriate envelope.

        Returns:
            BotEnvelope if bulk delete detected, None otherwise
        """
        import re
        from datetime import datetime

        text_lower = request.user_text.lower()

        # Pattern: "delete all" / "clear all" / "remove all" / "clear everything"
        is_bulk_delete = any(phrase in text_lower for phrase in [
            'delete all', 'clear all', 'remove all', 'clear everything',
            'delete everything', 'remove everything'
        ])

        if not is_bulk_delete:
            return None

        # Determine filter type
        target_tasks = []
        filter_desc = ""

        # Check for type filter: "delete all meetings", "clear all work tasks"
        task_types = ['meeting', 'work', 'personal', 'break']
        for task_type in task_types:
            if task_type in text_lower:
                target_tasks = [s for s in request.schedules_snapshot if s['type'] == task_type]
                filter_desc = f"{task_type}s"
                break

        # Check for date filter: "delete all today", "clear today", "delete all this week"
        if not target_tasks:
            if 'today' in text_lower:
                today_str = request.now_iso_as_dt.date().isoformat()
                target_tasks = [s for s in request.schedules_snapshot if s['date'] == today_str]
                filter_desc = "today's tasks"
            elif 'this week' in text_lower or 'week' in text_lower:
                # Get current week's date range
                today = request.now_iso_as_dt.date()
                start_of_week = today - timedelta(days=today.weekday())
                end_of_week = start_of_week + timedelta(days=6)

                target_tasks = [
                    s for s in request.schedules_snapshot
                    if start_of_week <= datetime.fromisoformat(s['date']).date() <= end_of_week
                ]
                filter_desc = "this week's tasks"

        # If no specific filter, delete ALL tasks
        if not target_tasks and is_bulk_delete:
            target_tasks = request.schedules_snapshot.copy()
            filter_desc = "all tasks"

        if not target_tasks:
            return BotEnvelope(
                stage="PLAN_EDIT",
                user_facing=f"No {filter_desc} found to delete.",
                ask_confirmation=False
            )

        # Build confirmation message
        task_count = len(target_tasks)
        task_ids = [s['id'] for s in target_tasks]

        # Create preview of tasks to be deleted (show first 3)
        preview_tasks = target_tasks[:3]
        preview_list = ", ".join([f"**{s['title']}**" for s in preview_tasks])
        if task_count > 3:
            preview_list += f" and {task_count - 3} more"

        # Different messages based on scope
        if filter_desc == "all tasks":
            confirmation_msg = f"⚠️ **Delete all {task_count} tasks?** This will clear your entire schedule.\n\nTasks: {preview_list}\n\nAre you sure you want to delete everything? This cannot be undone."
        else:
            confirmation_msg = f"Delete {task_count} {filter_desc}?\n\nTasks: {preview_list}\n\nSave this?"

        proposal = {
            'action': 'bulk_delete',
            'ids': task_ids,
            'filter_desc': filter_desc
        }

        return BotEnvelope(
            stage="PLAN_EDIT",
            edit=proposal,
            user_facing=confirmation_msg,
            ask_confirmation=True,
            proposal=proposal
        )
