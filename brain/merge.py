# brain/merge.py
"""
Merger: Applies BotEnvelope actions to session state.
Centralizes state mutations from bot responses.
"""
from core.contracts import BotEnvelope
from core.state import (
    add_schedule, update_schedule, delete_schedule, mark_complete,
    push_bot, set_confirmation, clear_confirmation
)


def handle_envelope(st_session_state, envelope: BotEnvelope) -> bool:
    """
    Apply BotEnvelope to session state.
    
    Args:
        st_session_state: Streamlit session state
        envelope: Bot response envelope
        
    Returns:
        True if state was mutated (needs rerun), False otherwise
    """
    state_mutated = False
    
    # Always add user-facing message to chat
    if envelope.user_facing:
        push_bot(st_session_state, envelope.user_facing)
    
    # Handle confirmation flow
    if envelope.ask_confirmation and envelope.proposal:
        set_confirmation(st_session_state, envelope.proposal, envelope.stage)
        return False  # Don't rerun yet, wait for user response
    
    # Handle immediate actions (rare, usually we ask first)
    for action in envelope.immediate_actions:
        action_type = action.get('type')
        
        if action_type == 'create':
            add_schedule(
                st_session_state,
                title=action.get('title', 'New Task'),
                date_str=action.get('date'),
                start_time=action.get('start_time'),
                duration=action.get('duration', 60),
                end_time=action.get('end_time')
            )
            state_mutated = True
        
        elif action_type == 'update':
            update_schedule(
                st_session_state,
                schedule_id=action.get('id'),
                changes=action.get('changes', {})
            )
            state_mutated = True
        
        elif action_type == 'delete':
            delete_schedule(st_session_state, action.get('id'))
            state_mutated = True
        
        elif action_type == 'complete':
            mark_complete(st_session_state, action.get('id'))
            state_mutated = True
    
    return state_mutated
