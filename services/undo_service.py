import logging
from typing import Any, Dict, List, Optional

from aiosqlite import Connection
from config import DATABASE_PATH
from services.action_log_repository import ActionLogRepository
from services.database_service import AppError, DatabaseManager
from utils.types import Transaction

logger = logging.getLogger(__name__)
async def undo_service(admin_id: int):
    """orchestrates undo operation"""
    res = {'ok': True, 'msg': [], 'log_error': [], 'data': None}
    db = DatabaseManager(DATABASE_PATH)
    async with db.get_connection() as conn:
        action_log_repo = ActionLogRepository(conn)
        last_action = await action_log_repo.fetch_last_log(admin_id)
        if not last_action:
            res['msg'].append("No action available to be undone")
            return res
        payload = last_action["payload"]
        action_type = last_action["action_type"]

        try:
            undo_details, data = await execute_undo(conn, action_type, payload)
            res['data'] = data
            await conn.commit()
        except AppError as exc:
            res['ok'] = False
            res['msg'].append(str(exc))
            logger.info("AppError: " + str(exc))
            return res
        except Exception as exc:
            res['ok'] = False
            logger.error("Exception: " + str(exc))
            return res
        action_log_repo.delete_action_log(last_action["id"])
    
    res['data']['action_type'] = action_type

    feedback_msg = format_undo_msg(undo_details, action_type)
    res['msg'].append(feedback_msg)
    return res

async def execute_undo(conn, action_type, payload):
    """
    Returns (undo_details, data)
    """
    data = {}
    undo_details = None

    match action_type:
        case "add_customer":
            undo_details = await undo_add_customer(conn, **payload)
            data['customer_id'] = payload['customer_id']
        case "add_transaction":
            undo_details = await undo_add_transaction(conn, payload['transaction_id'])
            data['customer_id'] = payload['customer_id']
        case "delete_customer":
            undo_details = await undo_delete_customer(conn, **payload)
        case "rename_customer":
            undo_details = await undo_update_customer_name(conn, **payload)
            data['customer_id'] = payload['customer_id']
            data['new_name'] = undo_details['Current Name']

        case "change_phone":
            undo_details = await undo_update_customer_phone(**payload)

    return undo_details, data



async def undo_delete_customer(
    conn: Connection,
    customer_id: int,
    admin_id: int,
    phone: Optional[str],
    fullname: str,
    created_at: str,
    balance: float,
    customer_transactions: List[Transaction],
) -> Dict[str, Any]:
    """Undo customer deletion (restore customer and transactions)."""
    from services.customer_repository import CustomerRepository
    from services.transaction_repository import TransactionRepository

    customer_repo = CustomerRepository(conn)
    transaction_repo = TransactionRepository(conn)

    # re-Create Deleted customer
    temp_id = await customer_repo.add_customer(fullname, phone, admin_id)
    # restore old meta-info and transactions
    await customer_repo.update_customer(temp_id, customer_id, created_at, balance)
    await transaction_repo.restore_transactions(customer_transactions)

    undo_details = {
        "Full Name": fullname.upper(),
        "Phone": phone,
        "Balance": balance,
    }
    return undo_details

async def undo_add_customer(
    conn: Connection, customer_id: int, admin_id: int
) -> Dict[str, Any]:
    """Undo customer addition (delete customer)."""
    from services.customer_repository import CustomerRepository

    customer_repo = CustomerRepository(conn)
    customer = await customer_repo.get_customer_by_id(customer_id, admin_id)
    await customer_repo.delete_customer(customer_id, admin_id)

    undo_details = {
        "Full Name": customer["fullname"],
        "Phone": customer["phone"],
        "Balance": customer["balance"],
    }
    return undo_details

async def undo_update_customer_name(
    conn: Connection,
    admin_id: int,
    customer_id: int,
    new_name: str,
    old_name: str,
) -> Dict[str, str]:
    """Undo customer name update."""
    from services.customer_repository import CustomerRepository

    customer_repo = CustomerRepository(conn)
    await customer_repo.update_customer_name(old_name, customer_id, admin_id)

    return {
        "Was Renamed to": new_name,
        "Current Name": old_name,
    }

async def undo_add_transaction(conn: Connection, transaction_id: int) -> Dict[str, str]:
    """Undo transaction addition (delete transaction)."""
    from services.transaction_repository import TransactionRepository

    transaction_repo = TransactionRepository(conn)
    result = await transaction_repo.delete_transaction_with_id(transaction_id)

    return {
        "Transfer": result["Removed Transaction"],
        "Customer id": result["Customer id"],
    }

async def undo_update_customer_phone(
    conn: Connection,
    admin_id: int,
    customer_id: int,
    new_phone: str,
    old_phone: Optional[str],
) -> Dict[str, str]:
    """Undo customer phone update."""
    from services.customer_repository import CustomerRepository
    customer_repo = CustomerRepository(conn)
    await customer_repo.update_customer_phone(old_phone, customer_id, admin_id)

    return {
        "Phone Was Updated to": new_phone,
        "Current Phone": old_phone,
    }


# undo utils
def format_undo_msg(details: dict, action_type):
    print(details)
    undo_details = "\n".join(
        f"  ■ <b>{k}:</b> {details[k]}"
        for k in details
    )

    return "\n".join([
        "<b>「✦ Undo Complete ✦」</b>",
        "    ─•────",
        f"● The <b>{action_type}</b> command has been cancelled.",
        undo_details,
])