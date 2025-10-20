# brain/router.py
"""
Router: Intent classification to determine which bot should handle the request.
Uses keyword rules + LLM tie-breaker for ambiguous cases.
"""
from typing import Optional
from core.contracts import RouteDecision, Stage
from core.llm import LLM


class Router:
    """Routes user messages to appropriate bot based on intent."""
    
    def __init__(self, llm: LLM, identity_path: str = "identities/router.txt"):
        """
        Initialize router.
        
        Args:
            llm: LLM instance for tie-breaking
            identity_path: Path to router identity file
        """
        self.llm = llm
        self.identity = self._load_identity(identity_path)
    
    def _load_identity(self, path: str) -> str:
        """Load router identity from file."""
        try:
            with open(path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            return "Classify user intent into: PLAN_CREATE, PLAN_EDIT, PLAN_CHECK, or OTHER."
    
    def route(self, user_text: str, awaiting_confirmation: bool = False) -> RouteDecision:
        """
        Route user message to appropriate stage.
        
        Args:
            user_text: User's message
            awaiting_confirmation: If True, don't route (return current stage)
            
        Returns:
            RouteDecision with stage and confidence
        """
        # Don't re-route if awaiting confirmation
        if awaiting_confirmation:
            return RouteDecision(stage="OTHER", confidence=1.0)
        
        # Try keyword-based classification first
        keyword_decision = self._classify_by_keywords(user_text)
        
        # If high confidence, use it
        if keyword_decision.confidence >= 0.7:
            return keyword_decision
        
        # Otherwise, use LLM tie-breaker
        llm_decision = self._classify_by_llm(user_text)
        
        return llm_decision if llm_decision else keyword_decision
    
    def _classify_by_keywords(self, text: str) -> RouteDecision:
        """
        Classify using keyword rules.
        
        Returns:
            RouteDecision with confidence based on keyword matches
        """
        text_lower = text.lower()
        
        # PLAN_CREATE keywords
        create_keywords = [
            'add', 'schedule', 'create', 'plan', 'book', 'set up', 'set',
            'block time', 'block', 'reminder', 'remind', 'new task', 'new'
        ]
        create_score = sum(1 for kw in create_keywords if kw in text_lower)
        
        # PLAN_EDIT keywords
        edit_keywords = [
            'move', 'reschedule', 'change', 'delay', 'extend', 'rename',
            'delete', 'remove', 'cancel', 'shorten', 'postpone', 'shift',
            'update', 'modify', 'edit', 'complete', 'done', 'finish'
        ]
        edit_score = sum(1 for kw in edit_keywords if kw in text_lower)
        
        # PLAN_CHECK keywords
        check_keywords = [
            'show', "what's", 'view', 'list', 'display', 'see',
            'agenda', 'calendar', 'schedule', 'due', 'upcoming',
            'today', 'tomorrow', 'week', 'month', 'status'
        ]
        check_score = sum(1 for kw in check_keywords if kw in text_lower)
        
        # OTHER keywords
        other_keywords = [
            'help', 'settings', 'timezone', 'about', 'how', 'what can',
            'role', 'rules', 'explain', 'configure'
        ]
        other_score = sum(1 for kw in other_keywords if kw in text_lower)
        
        # Find highest score
        scores = [
            (create_score, "PLAN_CREATE"),
            (edit_score, "PLAN_EDIT"),
            (check_score, "PLAN_CHECK"),
            (other_score, "OTHER")
        ]
        scores.sort(reverse=True)
        
        best_score, best_stage = scores[0]
        
        # Calculate confidence
        if best_score == 0:
            # No keywords matched, default to OTHER with low confidence
            return RouteDecision(stage="OTHER", confidence=0.3)
        
        total_score = sum(s[0] for s in scores)
        confidence = min(best_score / max(total_score, 1), 0.9)
        
        return RouteDecision(stage=best_stage, confidence=confidence)
    
    def _classify_by_llm(self, text: str) -> Optional[RouteDecision]:
        """
        Use LLM to classify intent.
        
        Returns:
            RouteDecision or None if LLM fails
        """
        prompt = f"""
Classify this user message into ONE of these categories:
- PLAN_CREATE: User wants to add/schedule a new task or event
- PLAN_EDIT: User wants to modify/delete an existing task
- PLAN_CHECK: User wants to view their schedule/tasks
- OTHER: Help, settings, or other meta requests

User message: "{text}"

Respond with ONLY a JSON object like:
{{"stage": "PLAN_CREATE", "confidence": 0.9}}
"""

        try:
            result = self.llm.classify_json(
                system_instruction=self.identity,
                prompt=prompt,
                schema_hint='{"stage": "PLAN_CREATE|PLAN_EDIT|PLAN_CHECK|OTHER", "confidence": 0.0-1.0}'
            )

            if result and 'stage' in result:
                return RouteDecision(
                    stage=result['stage'],
                    confidence=result.get('confidence', 0.7)
                )
        except Exception as e:
            # If LLM fails, return None to fall back to keyword routing
            pass

        return None
