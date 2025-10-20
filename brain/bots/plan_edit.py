# brain/bots/plan_edit.py
"""
Edit Bot: Handles PLAN_EDIT stage.
Identifies target task and proposes changes.
"""
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
        
        # Use LLM to identify target and changes
        schedules_text = "\n".join([
            f"- ID: {s['id']}, Title: {s['title']}, Date: {s['date']}, Time: {s['start_time']}"
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
        
        result = self.llm.classify_json(
            system_instruction=self.identity,
            prompt=prompt,
            schema_hint='{"action": "delete|complete|update", "id": "...", "changes": {...}}'
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
