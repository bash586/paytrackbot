"""Unified utilities module combining helpers and validation functions."""

from dataclasses import dataclass
from datetime import datetime
from functools import reduce
import re
from typing import Any, Dict, List, Optional
from config import *
from utils.types import SelectedCustomer, Transaction, ReportView


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


def normalize_fullname(name: str) -> str:
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

def is_valid_phone(number: str, pattern: str = DEFAULT_PHONE_PATTERN) -> bool:
    """Return True if the number matches a local/national phone format."""
    return re.match(pattern, number.strip()) is not None


def is_valid_name(name: str, pattern: str = DEFAULT_NAME_PATTERN) -> bool:
    """
    Return True if the name includes:
    - first and last name (required)
    - middle name (optional)
    - Maximum length: 30 characters
    """
    name_split = name.strip()
    return re.match(pattern, name_split) is not None and len(name_split) > 1


def validate_selected_customer(selected_customer: Optional[Dict]) -> tuple[bool, str]:
    """
    Validate that selected customer has required fields.
    
    Returns:
        tuple[bool, str]: (is_valid, error_message)
    """
    if not selected_customer:
        return False, "No customer selected"
    
    required_keys = {'customer_id', 'fullname', 'balance'}
    missing_keys = required_keys - set(selected_customer.keys())
    
    if missing_keys:
        return False, f"Invalid customer state: missing {missing_keys}"
    
    if not isinstance(selected_customer['customer_id'], int):
        return False, "Invalid customer state: customer_id is not an integer"
    
    return True, ""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def get_args(msg_txt: str, args_count: int = 3) -> list[str]:
    """Parse command or message text into arguments."""
    if not msg_txt or msg_txt == '':
        return []
    args_txt = msg_txt.strip()
    contains_command = args_txt[0] == '/'
    args_txt = None
    if contains_command:
        parts = msg_txt.strip().split(maxsplit=1)
        args_txt = parts[1] if len(parts) > 1 else ""
    else:
        args_txt = msg_txt
    return split_args(args_txt.strip(), args_count)


def split_args(args_txt: str, args_count: int) -> list[str]:
    """Split arguments by newline character."""
    if not args_txt:
        return []
    args: list[str] = []
    while args_txt and len(args) < args_count:
        head, *tail = args_txt.split("\n", 1)
        args.append(head.strip())
        args_txt = tail[0].strip() if len(tail) > 0 else ""
    return args


def parse_pagination_cursor(cursor_str: str, mode: str) -> tuple[bool, Optional[Any]]:
    """
    Parse pagination cursor from callback data.
    
    Args:
        cursor_str: Cursor string from callback data
        mode: Report view mode
    
    Returns:
        tuple[bool, Optional]: (is_valid, parsed_cursor)
    """
    if cursor_str == '0' or cursor_str == 'None':
        return True, None
    
    try:
        if mode in (ReportView.DUE_CUSTOMERS, ReportView.OVERPAID_CUSTOMERS):
            # Composite cursor: balance,id
            parts = cursor_str.split(',')
            if len(parts) != 2:
                if parts == '':
                    return True , 0
                raise ValueError(f"Expected 2 cursor parts, got {len(parts)}")
            return True, (float(parts[0]), int(parts[1]))
        elif mode == ReportView.CUSTOMER_TRANSACTION_HISTORY:
            # Integer cursor
            return True, int(cursor_str)
        else:
            return False, None
    except (ValueError, IndexError):
        return False, None


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_info_html(info: dict, recent_actions_formatted: str) -> str:
    """Return HTML formatted customer info for replies."""
    return f"""<b>「✦{info['fullname'].upper()}✦」</b>
  ─•────
Phone: <b><code>{info['phone']}</code></b>

Balance: <b>{info['balance']:.1f}</b>
Total Payments: <b>{info['payments']:.1f}</b>
Total Sales: <b>{info['sales']:.1f}</b>

Recent Transactions:
<blockquote>
{recent_actions_formatted}
</blockquote>
    """


def format_transaction(
    transaction: Transaction,
    is_last: bool,
    include_details: bool = False,
) -> str:
    """Format a single transaction for display."""
    parts: list[str] = []

    parts.append(
        f"<b>{'-' if transaction['type'] == 'sale' else '+'} "
        f"{transaction['amount']:.1f}</b>\n"
    )

    parts.append(f"                    <b>{transaction['created_at']}</b>\n")
    if include_details and transaction['description']:
        parts.append(
            f"\n<b>Description:</b>  {transaction['description']}\n"
        )

    if not is_last:
        parts.append("  ────୨ৎ────\n")
    else:
        parts.append("────୨ৎ────\n\n")

    return "".join(parts)


def format_enum_members(enum_cls) -> str:
    """Format enum members as comma-separated quoted values."""
    return ",".join(f"'{m.value}'" for m in enum_cls)


def format_date(dt_str: str) -> str:
    """Format datetime string to readable format."""
    dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
    return dt.strftime('%H:%M%p • %d %b %Y')


# ---------------------------------------------------------------------------
# Response object for commands/operations
# ---------------------------------------------------------------------------

@dataclass
class OperationResponse:
    """Standardized response object for command/operation execution.
    
    Handles success/failure status with user-facing and logging messages.
    Validates and sets defaults in __post_init__.
    """
    ok: bool = False
    error_msg: str = ""
    user_msg: Optional[str] = None
    log_msg: Optional[List[str]] = None
    
    def __post_init__(self):
        """Validate and set defaults after initialization."""
        if self.user_msg is None:
            self.user_msg = self.error_msg
        
        if self.log_msg is None:
            self.log_msg = [self.error_msg] if self.error_msg else []
    
    def to_dict(self) -> Dict:
        """Convert to dict format for backwards compatibility."""
        return {
            'ok': self.ok,
            'msg': [self.user_msg] if self.user_msg else [],
            'log_msg': self.log_msg
        }


def build_error_response(
    ok: bool = False,
    error_msg: str = "",
    user_msg: Optional[str] = None,
    log_msg: Optional[List[str]] = None
) -> Dict:
    """
    Build standardized error response dictionary.
    
    Deprecated: Use OperationResponse instead.
    
    Args:
        ok: Whether the operation succeeded
        error_msg: Internal error message for logging
        user_msg: User-facing message (defaults to error_msg if not provided)
        log_msg: List of log messages (defaults to [error_msg] if not provided)
    
    Returns:
        dict: Response object with ok, msg, log_msg keys
    """
    return OperationResponse(ok, error_msg, user_msg, log_msg).to_dict()


