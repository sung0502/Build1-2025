# brain/bots/plan_check.py
"""
Check Bot: Handles PLAN_CHECK stage.
Displays schedules in a clean, readable format.
"""
from datetime import datetime, timedelta
from core.contracts import BotRequest, BotEnvelope
from core.llm import LLM


class CheckBot:
    """Bot for checking/viewing schedules."""
    
    def __init__(self, llm: LLM, identity_path: str = "identities/checker.txt"):
        """
        Initialize check bot.
        
        Args:
            llm: LLM instance
            identity_path: Path to checker identity file
        """
        self.llm = llm
        self.identity = self._load_identity(identity_path)
    
    def _load_identity(self, path: str) -> str:
        """Load checker identity from file."""
        try:
            with open(path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            return "Show schedule clearly with emoji and short lines. Group by day."
    
    def run(self, request: BotRequest) -> BotEnvelope:
        """
        Process check request.
        
        Args:
            request: BotRequest with user input
            
        Returns:
            BotEnvelope with formatted schedule display
        """
        if not request.schedules_snapshot:
            return BotEnvelope(
                stage="PLAN_CHECK",
                user_facing="📅 Your schedule is empty. Ready to add some tasks?",
                ask_confirmation=False
            )
        
        # Determine scope (today vs week)
        text_lower = request.user_text.lower()
        if any(word in text_lower for word in ['today', 'tonight']):
            scope = 'today'
        elif any(word in text_lower for word in ['week', 'weekly', '7 days']):
            scope = 'week'
        else:
            # Default to today if ambiguous
            scope = 'today'
        
        # Filter schedules
        today = request.now_iso_as_dt.date()
        
        if scope == 'today':
            filtered = [s for s in request.schedules_snapshot if s['date'] == today.isoformat()]
            title = "📅 Today's Schedule"
        else:
            start_week = today - timedelta(days=today.weekday())
            end_week = start_week + timedelta(days=6)
            filtered = []
            for s in request.schedules_snapshot:
                try:
                    s_date = datetime.fromisoformat(s['date']).date()
                    if start_week <= s_date <= end_week:
                        filtered.append(s)
                except:
                    continue
            title = "📅 This Week's Schedule"
        
        if not filtered:
            if scope == 'today':
                return BotEnvelope(
                    stage="PLAN_CHECK",
                    user_facing="📅 Nothing scheduled for today. Enjoy your free time!",
                    ask_confirmation=False
                )
            else:
                return BotEnvelope(
                    stage="PLAN_CHECK",
                    user_facing="📅 Nothing scheduled this week. Time to plan ahead!",
                    ask_confirmation=False
                )
        
        # Format schedules
        lines = [title, ""]
        
        if scope == 'today':
            for s in filtered:
                emoji = self._get_emoji(s)
                status = "✅" if s.get('completed') else "⏰"
                time_str = s['start_time']
                if s.get('end_time'):
                    time_str += f" - {s['end_time']}"
                lines.append(f"{status} {emoji} **{s['title']}** at {time_str}")
        else:
            # Group by date
            by_date = {}
            for s in filtered:
                by_date.setdefault(s['date'], []).append(s)
            
            for date_str in sorted(by_date.keys()):
                date_obj = datetime.fromisoformat(date_str).date()
                day_name = date_obj.strftime("%A, %b %d")
                lines.append(f"\n**{day_name}**")
                
                for s in by_date[date_str]:
                    emoji = self._get_emoji(s)
                    status = "✅" if s.get('completed') else "⏰"
                    time_str = s['start_time'][:5]  # HH:MM only
                    lines.append(f"  {status} {emoji} {s['title']} at {time_str}")
        
        display_text = "\n".join(lines)
        
        return BotEnvelope(
            stage="PLAN_CHECK",
            check={'display': display_text},
            user_facing=display_text,
            ask_confirmation=False
        )
    
    def _get_emoji(self, schedule: dict) -> str:
        """Get emoji for schedule type."""
        type_map = {
            'work': '💼',
            'meeting': '🤝',
            'personal': '🏃',
            'break': '☕'
        }
        return type_map.get(schedule.get('type', 'work'), '📅')
