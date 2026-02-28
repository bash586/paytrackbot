from typing import Optional
from utils.utils import (
    normalize_fullname,
    normalize_phone,
    is_valid_name,
    is_valid_phone,
    get_selected_customer,
    set_selected_customer,
    update_context,
)
from services.customer_repository import CustomerRepository
from services.database_service import DatabaseManager, AppError


async def select_customer(customer_id: int, admin_id: int, db_manager: DatabaseManager, user_data: dict) -> Optional[dict]:
    """Fetch customer and update the user's selected customer state."""
    customer_repo = CustomerRepository(db_manager.conn)
    customer = await customer_repo.get_customer_by_id(customer_id, admin_id)
    if not customer:
        return None

    set_selected_customer(
        user_data,
        {k: customer[k] for k in ("customer_id", "fullname", "balance")}
    )
    return customer


async def add_customer(
    fullname: str,
    phone: str,
    admin_id: int,
    db_manager: DatabaseManager,
    user_data: dict,
    with_logging: bool,
    customer_id: int = None,
) -> dict:
    """Validate inputs and add a customer to the database.
    
    Returns:
        dict: Response with 'ok' (bool), 'msg' (list), 'log_msg' (list)
    """
    res = {'ok': True, 'msg': [], 'log_msg': []}
    fullname, phone = normalize_fullname(fullname), normalize_phone(phone)

    # validate inputs
    if not is_valid_name(fullname):
        err_msg = (
            "Invalid Name: name should include:\n"
            " ● First and Last Name (required)\n"
            " ● Middle name                (optional)"
        )
        res['ok'] = False
        res['msg'].append(err_msg)
        res['log_msg'].append(f"Validation error: {err_msg}")
        return res

    if not is_valid_phone(phone):
        err_msg = "Invalid Phone Number"
        res['ok'] = False
        res['msg'].append(err_msg)
        res['log_msg'].append(f"Validation error: {err_msg}")
        return res

    try:
        customer_repo = CustomerRepository(db_manager.conn)
        customer_id = await customer_repo.add_customer(fullname, phone, admin_id)
        res['log_msg'].append(f"Customer created: {fullname} ({phone})")
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

    # if customer is created via 'addcustomer' command
    if with_logging:
        await select_customer(customer_id, admin_id, db_manager, user_data)
        res['msg'].append(f"New Customer: added <b>{fullname.upper()}</b>")
    
    return res

async def delete_customer(
    customer_id: int,
    admin_id: int,
    db_manager: DatabaseManager,
    user_data: dict,
    with_logging: bool = True,
) -> dict:
    """Delete customer from database and clear selection if necessary."""
    try:
        customer_repo = CustomerRepository(db_manager.conn)
        await customer_repo.delete_customer(customer_id, admin_id)
    except AppError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:
        return {"ok": False, "error": "Something went wrong. Please try again later."}

    # remove customer from context
    selected_customer = get_selected_customer(user_data)
    if selected_customer and selected_customer["customer_id"] == customer_id:
        set_selected_customer(user_data, None)

    return {"ok": True, "error": None}


async def rename_customer(
    new_name: str,
    customer_id: int,
    admin_id: int,
    db_manager: DatabaseManager,
    user_data: dict,
    with_logging: bool = True,
) -> dict:
    """Validate and update customer name, updating context if selected."""
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
        customer_repo = CustomerRepository(db_manager.conn)
        name_change_info = await customer_repo.update_customer_name(new_name, customer_id, admin_id)
    except AppError as exc:
        return {"ok": False, "error": str(exc), "new name": new_name}
    except Exception:
        return {"ok": False, "error": "Something went wrong. Please try again later.", "new name": new_name}

    # update context
    selected_customer = get_selected_customer(user_data)
    if selected_customer and selected_customer.get("customer_id") == customer_id:
        update_context(user_data, fullname=new_name)

    return {"ok": True, "error": None, "new name": new_name}


async def change_phone(
    new_phone: str,
    customer_id: int,
    admin_id: int,
    db_manager: DatabaseManager,
    user_data: dict,
    with_logging: bool = True,
) -> dict:
    """Validate and update customer phone number."""
    new_phone = normalize_phone(new_phone)
    if not is_valid_phone(new_phone):
        return {"ok": False, "error": f"Invalid phone number: {new_phone}", "proposed_phone": new_phone}

    try:
        customer_repo = CustomerRepository(db_manager.conn)
        result = await customer_repo.update_customer_phone(new_phone, customer_id, admin_id)
    except AppError as exc:
        return {"ok": False, "error": str(exc), "proposed_phone": new_phone}
    except Exception:
        return {"ok": False, "error": "Something went wrong. Please try again later.", "proposed_phone": new_phone}

    return {"ok": True, "error": None, "proposed_phone": new_phone}