# brain/bots/plan_create.py
"""
Create Bot: Handles PLAN_CREATE stage.
Extracts task details and asks for confirmation.
"""
from core.contracts import BotRequest, BotEnvelope
from core.llm import LLM
from core.timeparse import parse_create_minimum


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
        # First try quick parsing
        title, date_str, start_time, duration = parse_create_minimum(
            request.user_text,
            request.now_iso_as_dt.date()
        )
        
        # Calculate end_time
        h, m = map(int, start_time.split(":"))
        total_minutes = h * 60 + m + duration
        end_h, end_m = divmod(total_minutes, 60)
        end_time = f"{end_h:02d}:{end_m:02d}"
        
        # Build proposal
        proposal = {
            'title': title,
            'date': date_str,
            'start_time': start_time,
            'end_time': end_time,
            'duration': duration
        }
        
        # Use LLM to generate friendly confirmation message
        prompt = f"""
User wants to create a task with these details:
- Title: {title}
- Date: {date_str}
- Time: {start_time} - {end_time}
- Duration: {duration} minutes

Generate a friendly confirmation message asking the user to confirm.
Keep it brief and natural. End with "Save this?"

Current time: {request.now_iso}
Timezone: {request.tz_name}
"""
        
        confirmation_msg = self.llm.generate(
            system_instruction=self.identity,
            prompt=prompt,
            temperature=0.6,
            max_tokens=256
        )
        
        if not confirmation_msg or "save this?" not in confirmation_msg.lower():
            # Fallback confirmation
            confirmation_msg = f"I'll add **{title}** on {date_str} from {start_time} to {end_time}. Save this?"
        
        return BotEnvelope(
            stage="PLAN_CREATE",
            create=proposal,
            user_facing=confirmation_msg,
            ask_confirmation=True,
            proposal=proposal
        )
