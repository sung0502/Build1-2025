# core/contracts.py
"""
Contracts module: Type definitions and data structures for TimeBuddy.
Defines the communication protocol between Router, Bots, and Merger.
"""
from typing import Literal, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

# Stage types
Stage = Literal["PLAN_CREATE", "PLAN_EDIT", "PLAN_CHECK", "OTHER"]


@dataclass
class RouteDecision:
    """Decision from Router about which bot to invoke."""
    stage: Stage
    confidence: float  # 0.0 to 1.0
    slots_needed: Optional[list[str]] = None  # e.g., ["title", "date"]
    
    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0-1, got {self.confidence}")


@dataclass
class BotRequest:
    """Standardized request to any bot."""
    user_text: str
    now_iso: str  # ISO datetime string
    tz_name: str  # IANA timezone name
    schedules_snapshot: list[dict]  # Current schedules
    system_identity: str  # Bot-specific identity/prompt
    chat_history: list[dict] = field(default_factory=list)  # Recent messages
    
    @property
    def now_iso_as_dt(self) -> datetime:
        """Convenience: parse now_iso to datetime."""
        return datetime.fromisoformat(self.now_iso)


@dataclass
class BotEnvelope:
    """Standardized response from any bot."""
    stage: Stage
    
    # Bot-specific action data (only one should be populated)
    create: Optional[dict] = None  # {title, date, start_time, duration}
    edit: Optional[dict] = None    # {id, changes}
    check: Optional[dict] = None   # {display_data}
    other: Optional[dict] = None   # {message}
    
    # User-facing message
    user_facing: str = ""
    
    # Confirmation flow
    ask_confirmation: bool = False
    proposal: Optional[dict] = None  # Data pending user confirmation
    
    # Optional immediate actions (rare, usually we ask first)
    immediate_actions: list[dict] = field(default_factory=list)
    
    def __post_init__(self):
        # Validate that exactly one action type is set
        action_count = sum([
            self.create is not None,
            self.edit is not None,
            self.check is not None,
            self.other is not None
        ])
        if action_count > 1:
            raise ValueError("BotEnvelope should have at most one action type set")
