# brain/bots/other.py
"""
Other Bot: Handles OTHER stage.
Responds to help, settings, and meta requests.
"""
from core.contracts import BotRequest, BotEnvelope
from core.llm import LLM


class OtherBot:
    """Bot for handling meta requests (help, settings, etc)."""
    
    def __init__(self, llm: LLM, identity_path: str = "identities/other.txt"):
        """
        Initialize other bot.
        
        Args:
            llm: LLM instance
            identity_path: Path to other identity file
        """
        self.llm = llm
        self.identity = self._load_identity(identity_path)
    
    def _load_identity(self, path: str) -> str:
        """Load other bot identity from file."""
        try:
            with open(path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            return "Handle help and settings briefly. Redirect to scheduling tasks."
    
    def run(self, request: BotRequest) -> BotEnvelope:
        """
        Process other/meta request.
        
        Args:
            request: BotRequest with user input
            
        Returns:
            BotEnvelope with helpful response
        """
        text_lower = request.user_text.lower()
        
        # Quick responses for common queries
        if any(word in text_lower for word in ['help', 'how', 'what can']):
            return BotEnvelope(
                stage="OTHER",
                user_facing=self._help_message(),
                ask_confirmation=False
            )
        
        if 'timezone' in text_lower or 'time zone' in text_lower:
            return BotEnvelope(
                stage="OTHER",
                user_facing=f"Your current timezone is **{request.tz_name}**. You can change it in the sidebar settings. What would you like to schedule?",
                ask_confirmation=False
            )
        
        # Use LLM for other cases
        prompt = f"""
User message: "{request.user_text}"
Current timezone: {request.tz_name}
Current time: {request.now_iso}

This is a meta/help request. Provide a brief, friendly response.
Then redirect the user back to scheduling tasks.
Keep it under 3 sentences.
"""
        
        response = self.llm.generate(
            system_instruction=self.identity,
            prompt=prompt,
            temperature=0.6,
            max_tokens=256
        )
        
        if not response:
            response = "I'm here to help you manage your schedule! What would you like to do?"
        
        return BotEnvelope(
            stage="OTHER",
            other={'message': response},
            user_facing=response,
            ask_confirmation=False
        )
    
    def _help_message(self) -> str:
        """Return help message."""
        return """👋 **I'm TimeBuddy!** Here's what I can help you with:

**Create tasks:**
- "Add team meeting tomorrow at 2pm for 1 hour"
- "Schedule workout at 7am"

**Edit tasks:**
- "Move my workout to 8am"
- "Cancel the 3pm meeting"

**Check schedule:**
- "Show me today's schedule"
- "What's on for this week?"

Just tell me what you need, and I'll help you manage your time!"""
