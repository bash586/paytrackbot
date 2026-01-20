from typing import Optional
from bot.helpers import (
    normalize_fullname,
    normalize_phone,
    is_valid_name,
    is_valid_phone,
    get_selected_customer,
    set_selected_customer,
    update_context,
)
from bot.database_manager import DatabaseManager, AppError


async def select_customer(customer_id: int, admin_id: int, db_manager: DatabaseManager, user_data: dict) -> Optional[dict]:
    """Fetch customer and update the user's selected customer state."""
    customer = await db_manager.get_customer_by_id(customer_id, admin_id)
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
    """Validate inputs and add a customer to the database."""
    fullname, phone = normalize_fullname(fullname), normalize_phone(phone)

    # validate inputs
    if not is_valid_name(fullname):
        err_msg = """
        Invalid Name: name should include:
        - first and last name (required)
        - middle name (optional)
        """
        return {"ok": False, "error": err_msg}

    if not is_valid_phone(phone):
        return {"ok": False, "error": "Invalid Phone Number"}

    try:
        customer_id = await db_manager.add_customer(fullname, phone, admin_id, with_logging=with_logging)
    except AppError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:
        return {"ok": False, "error": "Something went wrong. Please try again later."}

    # if customer is created via 'addcustomer' command
    if with_logging:
        await select_customer(customer_id, admin_id, db_manager, user_data)
    return {"ok": True, "error": None}

async def delete_customer(
    customer_id: int,
    admin_id: int,
    db_manager: DatabaseManager,
    user_data: dict,
    with_logging: bool = True,
) -> dict:
    """Delete customer from database and clear selection if necessary."""
    try:
        await db_manager.delete_customer(customer_id, admin_id, with_logging)
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
            "error": """
                Invalid Name: name should include:
                - first and last name (required)
                - middle name (optional)
            """,
            "new name": new_name,
        }

    try:
        name_change_info = await db_manager.update_customer_name(new_name, customer_id, admin_id, with_logging)
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
        result = await db_manager.update_customer_phone(new_phone, customer_id, admin_id, with_logging)
    except AppError as exc:
        return {"ok": False, "error": str(exc), "proposed_phone": new_phone}
    except Exception:
        return {"ok": False, "error": "Something went wrong. Please try again later.", "proposed_phone": new_phone}

    return {"ok": True, "error": None, "proposed_phone": new_phone}