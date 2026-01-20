from datetime import datetime
from functools import reduce
import re
from typing import List, Optional
from config import *
from bot.types import SelectedCustomer


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def normalize_phone(phone: str) -> str:
    """Convert phone number to digits only (remove all non-digits)."""
    digits = re.sub(r"\D", "", phone)
    return digits


def normalize_name(name: str) -> str:
    """Normalize a single name (strip and lowercase)."""
    return name.strip().lower()


def normalize_fullname(
    name: str
) -> str:
    """Return fullname if it contains more than one word, otherwise returns empty string."""
    name_parts = re.split(r"\s+", normalize_name(name))
    if len(name_parts) < 2:
        return ""
    first, last = normalize_name(name_parts[0]), normalize_name(name_parts[-1])
    middle = ' '.join(normalize_name(p) for p in name_parts[1:-1])

    return f"{first} {middle + ' ' if len(middle)>0 else ''}{last}"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def is_valid_phone(
    number: str,
    pattern: str = DEFAULT_PHONE_PATTERN,
) -> bool:
    """Return True if the number matches a local/national phone format."""
    return re.match(pattern, number.strip()) is not None


def is_valid_name(
    name: str,
    pattern: str = DEFAULT_NAME_PATTERN
) -> bool:
    """
    Return True if the name includes:
    - first and last name (required)
    - middle name (optional)
    - Maximum length: 30 characters
    """
    name_split = name.strip()
    return re.match(pattern, name_split) is not None and len(name_split) > 1


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def get_args(msg_txt: str) -> List[str]:
    try:
        args_txt = msg_txt.split(" ", maxsplit=1)[1].strip('|')  # discard command part
    except IndexError:
        args_txt = ""
    args = args_txt.split("|")  # "|" is args delimiter
    refined_args = filter(lambda arg: len(arg) > 0, map(lambda item: item.strip(), args))  # remove unwanted spaces and empty arguments
    return list(refined_args)

# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def format_summary_html(summary: dict, recent_actions_formatted: str) -> str:
    """Return HTML formatted customer summary for replies."""
    return f"""<b>「✦{summary['fullname'].upper()}✦」</b>
  ─•────
Phone: <b><code>{summary['phone']}</code></b>

Total Payments: <b>{summary['payments']:.1f}</b>
Total Sales: <b>{summary['sales']:.1f}</b>
Balance: <b>{summary['balance']:.1f}</b>

Recent Transactions:
<blockquote>
{recent_actions_formatted}
</blockquote>
    """

def format_transaction(transaction: dict, is_last: bool) -> str:
    return "\n".join([
        f"<b>{'💸' if transaction['type'] == 'sale' else '💰'} {transaction['amount']:.1f}</b>",
        f"                  {transaction['created_at']}",
        '  ────୨ৎ────' if not is_last 
        else '────୨ৎ────\n\n   【 💸 = sale │ 💰 = payment 】 \n ',
        ' '
    ])

def format_enum_members(enum_cls) -> str:
    return ",".join(
        f"'{m.value}'" for m in enum_cls
    )

def format_date(dt_str: str)->str:
    dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
    return dt.strftime('%H:%M%p • %d %b %Y')
# ---------------------------------------------------------------------------
# Context state management
# ---------------------------------------------------------------------------
def get_selected_customer(user_data: dict) -> Optional[SelectedCustomer]:
    context_state = user_data.get("context_state", {})
    selected_customer = context_state.get("selected_customer", None)
    return selected_customer

def set_selected_customer(user_data: dict, selected_customer: Optional[SelectedCustomer] = None) -> None:
    context_state = user_data.setdefault('context_state', {})
    context_state['selected_customer'] = selected_customer

def rename_customer_state(user_data: dict, new_name: str)->None:
    # Backwards-compatible wrapper that updates the selected customer's fullname
    update_context(user_data, fullname=new_name)


def update_context(user_data: dict, fullname: str = None, balance: float = None, **kwargs) -> None:
    """Generic helper to update fields on the currently selected customer in user_data.

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
        