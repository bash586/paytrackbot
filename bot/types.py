from typing import TypedDict, Optional, Dict, Any, Union
from enum import Enum

class TransactionType(str, Enum):
    SALE = "sale"
    PAYMENT = "payment"


class ActionType(str, Enum):
    CHANGE_PHONE = "change_phone"
    ADD_CUSTOMER = "add_customer"
    ADD_TRANSACTION = "add_transaction"
    DELETE_CUSTOMER = "delete_customer"
    RENAME_CUSTOMER = "rename_customer"

ActionPayload = TypedDict(
    'ActionPayload',
    {
        'undo-args': Dict[str, Any],
        'more-info': Dict[str, Any],
    },
    total=False,
)

# -----------------------------------------------------------------------
# Database types
# -----------------------------------------------------------------------
class Customer(TypedDict):
    customer_id: int
    fullname: str
    phone: Optional[str]
    balance: float
    created_at: Optional[str]


class Transaction(TypedDict):
    id: int
    amount: float
    type: TransactionType
    customer_id: int
    admin_id: int
    description: Optional[str]
    created_at: str


class ActionLog(TypedDict):
    id: int
    admin_id: int
    customer_id: int
    action_type: ActionType
    payload: str
    created_at: str


SelectedCustomer = Customer

# -----------------------------------------------------------------------
# Report View Types
# -----------------------------------------------------------------------
class ReportView(str, Enum):
    DUE_CUSTOMERS = "due_customers"
    OVERPAID_CUSTOMERS = "overpaid_customers"
    OVERALL_SUMMARY = "overall_summary" 
    CUSTOMER_TRANSACTION_HISTORY = "customer_transaction_history"