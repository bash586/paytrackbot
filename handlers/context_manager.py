# Conversation context management

from typing import Dict, Optional
from utils.types import SelectedCustomer

def clear_conversation_ctx(user_data: Dict) -> None:
    """Clear all conversation-related context."""
    user_data['search_mode'] = None
    user_data['active_command_args'] = None
    user_data['active_command'] = None


def get_selected_customer(user_data: dict) -> Optional[SelectedCustomer]:
    """Get the currently selected customer from user context."""
    context_state = user_data.get("context_state", {})
    selected_customer = context_state.get("selected_customer", None)
    return selected_customer


def set_selected_customer(user_data: dict, selected_customer: Optional[SelectedCustomer] = None) -> None:
    """Set the currently selected customer in user context."""
    context_state = user_data.setdefault('context_state', {})
    context_state['selected_customer'] = selected_customer


def rename_customer_state(user_data: dict, new_name: str) -> None:
    """Update the selected customer's fullname in user context."""
    update_context(user_data, fullname=new_name)


def update_context(user_data: Dict, fullname: str = None, balance: float = None, **kwargs) -> None:
    """
    Generic helper to update fields on the currently selected customer in user_data.

    Only updates fields that are provided (not None). Additional keyword args
    will be set as-is on the selected customer dict.
    """
    context_state = user_data.setdefault('context_state', {})
    customer = context_state.get('selected_customer')
    if not customer:
        return

    if fullname is not None:
        customer['fullname'] = fullname
    if balance is not None:
        customer['balance'] = balance

    # Apply any other provided fields
    for k, v in kwargs.items():
        customer[k] = v
