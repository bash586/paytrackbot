from typing import List, Optional, Dict, Any

from aiosqlite import Connection
from config import DATABASE_PATH
from utils.types import ActionType
from utils.utils import (
    normalize_fullname,
    normalize_phone,
    is_valid_name,
    is_valid_phone,
)
from services.transaction_repository import TransactionRepository
from services.action_log_repository import ActionLogRepository
from services.customer_repository import CustomerRepository
from services.report_repository import ReportRepository
from services.database_service import DatabaseManager, AppError
import logging
logger = logging.getLogger(__name__)

async def get_customer(
    customer_id: int,
    admin_id: int,
) -> Optional[Dict[str, Any]]:
    """Fetch customer and update the user's selected customer state.
    
    Returns:
        dict: Customer data (customer_id, fullname, balance) or None if not found
    """
    try:
        db = DatabaseManager(DATABASE_PATH)
        async with db.get_connection() as conn:
            customer_repo = CustomerRepository(conn)
            customer = await customer_repo.get_customer_by_id(customer_id, admin_id)
        if not customer:
            return None

        return customer
    except Exception as exc:
        logger.error(f"Failed to select customer {customer_id}: {exc}")
        return None


async def get_customer_transactions(
    customer_id: int,
    admin_id: int,
    limit: int = 5,
    cursor: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch paginated transactions for a customer.
    
    Returns:
        dict: Page data with items, next_cursor, has_more
    """
    try:
        db = DatabaseManager(DATABASE_PATH)
        async with db.get_connection() as conn:
            report_repo = ReportRepository(conn)
            return await report_repo.fetch_transactions_page(customer_id, admin_id, limit, cursor)
    except Exception as exc:
        logger.error(f"Failed to fetch transactions for customer {customer_id}: {exc}")
        return None


async def add_customer(
    args: List,
    admin_id: int,
):
    """Validate inputs and add a customer to the database.

    Returns:
        dict: Response with 'ok' (bool), 'msg' (list), 'log_msg' (list)
    """
    res = {'ok': True, 'msg': [], 'log_msg': [], 'customer_id': None}

    if len(args) < 2:
        from config import INVALID_USAGE
        err_msg = INVALID_USAGE['addcustomer']
        res['ok'] = False
        res['msg'].append(err_msg)
        return res

    fullname = normalize_fullname(args[0])
    phone = normalize_phone(args[1])
    if not fullname or not phone:
        from config import INVALID_USAGE
        err_msg = INVALID_USAGE['addcustomer']
        res['ok'] = False
        res['msg'].append(err_msg)
        return res


    # validate inputs
    if not is_valid_name(fullname):
        err_msg = (
            f"Invalid Name: {fullname}\nname should include:\n"
            " ● First and Last Name (required)\n"
            " ● Middle name                (optional)"
        )
        res['ok'] = False
        res['msg'].append(err_msg)
        res['log_msg'].append(f"Validation error: {err_msg}")

    if not is_valid_phone(phone):
        err_msg = f"Invalid Phone: {phone}"
        res['ok'] = False
        res['msg'].append(err_msg)
        res['log_msg'].append(f"Validation error: {err_msg}")

    if not res['ok']:
        return res

    try:
        db = DatabaseManager(DATABASE_PATH)
        async with db.get_connection() as conn:
            customer_repo = CustomerRepository(conn)
            action_log_repo = ActionLogRepository(conn)
            customer_id = await customer_repo.add_customer(fullname, phone, admin_id)
            await action_log_repo.add_action_log(
                ActionType.ADD_CUSTOMER, admin_id, customer_id,
                payload={'customer_id': customer_id, 'admin_id': admin_id}
            )
            await conn.commit()

    except AppError as exc:
        res['ok'] = False
        err_msg = str(exc)
        res['msg'].append(err_msg)
        res['log_msg'].append(f"AppError: {err_msg}")
        return res

    except Exception as exc:
        res['ok'] = False
        err_msg = "Something went wrong. Please try again later."
        res['msg'].append(err_msg)
        res['log_msg'].append(f"Exception: {str(exc)}")
        return res

    res['log_msg'].append(f"Customer created: {fullname} ({phone})")
    # if customer is created via 'addcustomer' command
    from config import FEEDBACK_AVAILABLE_COMMANDS
    res['msg'].append(f"New Customer: added <b>{fullname.upper()}</b>\n\n" + FEEDBACK_AVAILABLE_COMMANDS)
    res['customer_id'] = customer_id
    return res


async def add_transaction(
    args: List, admin_id: int, customer_id: int, fullname: str,

):
    """Process and add a transaction."""
    res = {'ok': True, 'msg': [], 'log_msg': [], 'data': {}}
    description = "" if len(args) < 2 else args[1]
    try:
        from utils.utils import normalize_name
        amount = float(normalize_name(args[0]))
        type_ = 'sale' if amount < 0 else 'payment'
        amount = abs(amount)
    except ValueError:
        res["ok"] = False
        res["msg"].append("Invalid <b>amount</b> value: amount must be a number")
        return res

    amount = float(amount)
    res['log_msg'].append((f"adding a transaction for user with id :{admin_id}\n"
        "passed arguments:\n"
        f"amount:{amount}\n"
        f"description:\n{description}")
    )
   
    try:
        db = DatabaseManager(DATABASE_PATH)
        async with db.get_connection() as conn:
            trans_repo = TransactionRepository(conn)
            transaction_id = await trans_repo.add_transaction(amount, type_, description, customer_id, admin_id)
            action_log_repo = ActionLogRepository(conn)
            await action_log_repo.add_action_log (
                ActionType.ADD_TRANSACTION, admin_id, customer_id,
                payload = {
                    'customer_id': customer_id,
                    'admin_id': admin_id,
                    'transaction_id': transaction_id,
                }
            )
            customer_repo = CustomerRepository(conn)
            new_balance = (await customer_repo.get_customer_by_id(customer_id, admin_id))['balance']
            await conn.commit()
    except Exception as exc:
        res["ok"] = False
        res["msg"].append("Something went wrong. Please try again later.")
        res['log_msg'].append("error: " + str(exc))
        return res

    res['data']['new_balance'] = new_balance
    desc = f"<b>Description: </b> {description}" if len(args) > 1 else ''
    feedback_msg = (f"「 ✦<b>{fullname.upper()}</b>✦ 」\n"
                    "  ─•────\n"
                    f"Successfully added <b>{type_.upper()}</b> of <b>{amount:.2f}</b>\n"
                    f"{desc}"
                    f"\n<b>Account Balance: {new_balance:.2f}</b>")
    res["msg"].append(feedback_msg)
    return res

async def delete_customer(
    customer_id: int,
    admin_id: int,
) -> dict:
    """Delete customer from database.
    
    Returns:
        dict: {'ok': bool, 'error': str or None}
    """
    try:
        db = DatabaseManager(DATABASE_PATH)
        async with db.get_connection() as conn:
            customer_repo = CustomerRepository(conn)
            trans_repo = TransactionRepository(conn)
            customer = await customer_repo.get_customer_by_id(customer_id, admin_id, True)
            customer_trans = await trans_repo.get_customer_transactions(customer_id, admin_id)
            await customer_repo.delete_customer(customer_id, admin_id)
            action_log_repo = ActionLogRepository(conn)
            await action_log_repo.add_action_log (
                ActionType.DELETE_CUSTOMER, admin_id, customer_id,
                payload = {
                    'customer_transactions': customer_trans,
                    **customer
                }
            )
            await conn.commit()
    except Exception:
        return {"ok": False, "error": "Something went wrong. Please try again later."}

    return {"ok": True, "error": None}


async def rename_customer(
    old_name: str,
    new_name: str,
    customer_id: int,
    admin_id: int,
) -> dict:
    """Validate and update customer name.
    
    Returns:
        dict: {'ok': bool, 'error': str or None, 'new name': str}
    """
    logger.debug("Updating customer name: customer_id=%s new_name=%s", customer_id, new_name)
    new_name = normalize_fullname(new_name)
    if not is_valid_name(new_name):
        return {
            "ok": False,
            "error": (
                "Invalid Name: name should include:\n\n"
                " ● First and Last Name (required)\n"
                " ● Middle name                (optional)"
                )
            ,
            "new name": new_name,
        }

    try:
        db = DatabaseManager(DATABASE_PATH)
        async with db.get_connection() as conn:
            customer_repo = CustomerRepository(conn)
            await customer_repo.update_customer_name(new_name, customer_id, admin_id)
            action_log_repo = ActionLogRepository(conn)
            await action_log_repo.add_action_log (
                ActionType.RENAME_CUSTOMER, admin_id, customer_id,
                payload = {
                    "admin_id": admin_id,
                    "customer_id": customer_id,
                    "new_name": new_name,
                    "old_name": old_name
                }
            )
            await conn.commit()
            logger.info("Updated customer name: id=%s old=%s new=%s", customer_id, old_name, new_name)
    except AppError as exc:
        return {"ok": False, "error": str(exc), "new name": new_name}
    except Exception:
        return {"ok": False, "error": "Something went wrong. Please try again later.", "new name": new_name}

  

    return {"ok": True, "error": None, "new name": new_name}


async def change_phone(
    new_phone: str,
    customer_id: int,
    admin_id: int,
    
) -> dict:
    """Validate and update customer phone number.
    
    Returns:
        dict: {'ok': bool, 'error': str or None, 'proposed_phone': str}
    """
    logger.debug("Updating customer phone: customer_id=%s new_phone=%s", customer_id, new_phone)

    new_phone = normalize_phone(new_phone)
    if not is_valid_phone(new_phone):
        return {"ok": False, "error": f"Invalid phone number: {new_phone}", "proposed_phone": new_phone}

    try:
        db = DatabaseManager(DATABASE_PATH)
        async with db.get_connection() as conn:
            customer_repo = CustomerRepository(conn)
            phone_change_dict = await customer_repo.update_customer_phone(new_phone, customer_id, admin_id)
            
            action_log_repo = ActionLogRepository(conn)
            await action_log_repo.add_action_log (
                ActionType.CHANGE_PHONE, admin_id, customer_id,
                payload = {
                    "admin_id": admin_id,
                    "customer_id": customer_id,
                    "new_phone": new_phone,
                    "old_phone": phone_change_dict['Old Phone']
                }
            )

            await conn.commit()
            logger.info("Updated customer phone: id=%s", customer_id)
    except AppError as exc:
        return {"ok": False, "error": str(exc), "proposed_phone": new_phone}
    except Exception:
        return {"ok": False, "error": "Something went wrong. Please try again later.", "proposed_phone": new_phone}

    return {"ok": True, "error": None, "proposed_phone": new_phone}


async def get_customer_info(customer_id: int, admin_id: int) -> Optional[Dict[str, Any]]:
    """Fetch customer info (profile + recent transactions + totals).
    
    Returns:
        dict: Customer info data or None if error occurs
    """
    try:
        db = DatabaseManager(DATABASE_PATH)
        async with db.get_connection() as conn:
            customer_repo = CustomerRepository(conn)
            info = await customer_repo.get_customer_info(customer_id, admin_id)
            return info
    except Exception as exc:
        logger.error(f"Failed to fetch customer info {customer_id}: {exc}")
        return None

async def get_search_results_service(query, limit, admin_id) -> Optional[Dict[str, Any]]:
    try:
        db = DatabaseManager(DATABASE_PATH)
        async with db.get_connection() as conn:
            customer_repo = CustomerRepository(conn)
            customers = await customer_repo.search_customers(query, limit, admin_id)
            return customers
    except Exception as exc:
        logger.error(f"Failed to fetch Search Results {admin_id}: {exc}")
        return None