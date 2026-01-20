from bot.database_manager import DatabaseManager
from bot.helpers import get_selected_customer, set_selected_customer, update_context

async def execute_undo(db: DatabaseManager, action_type: str, payload: dict, user_data):
    inverse = {
        "rename_customer": undo_update_customer_name,
        "change_phone": undo_update_customer_phone,
        "delete_customer": undo_delete_customer,
        "add_customer": undo_add_customer,
        "add_transaction": undo_add_transaction,
    }
    inverse_function = inverse[action_type]

    undo_args = payload['undo-args']
    undo_details = await inverse_function(db, user_data, undo_args)
    feedback_msg = format_undo_msg(undo_details, action_type)
    return feedback_msg

async def undo_update_customer_name(db:DatabaseManager, user_data, payload):
    undo_details = await db.undo_update_customer_name(**payload)
    selected_customer = get_selected_customer(user_data)
    if selected_customer and selected_customer['customer_id'] == payload['customer_id']:
        update_context(user_data, fullname=undo_details['Current Name'])
    return undo_details

async def undo_update_customer_phone(db:DatabaseManager, user_data, payload):
    undo_details = await db.undo_update_customer_phone(**payload)
    return undo_details

async def undo_add_customer(db:DatabaseManager, user_data, payload):
    undo_details = await db.undo_add_customer(**payload)
    # update context
    selected_customer = get_selected_customer(user_data)
    if selected_customer and selected_customer['customer_id'] == payload['customer_id']:
        set_selected_customer(user_data, None)
    return undo_details

async def undo_delete_customer(db:DatabaseManager, user_data, payload):
    undo_details = await db.undo_delete_customer(**payload)
    return undo_details

async def undo_add_transaction(db:DatabaseManager, user_data, payload):
    undo_details = await db.undo_add_transaction(payload['transaction_id'])
    # update context
    selected_customer = get_selected_customer(user_data)
    customer_id = payload['customer_id']
    admin_id = payload['admin_id']

    if selected_customer and selected_customer['customer_id'] == customer_id:
        new_balance = (await db.get_customer_by_id(customer_id, admin_id))['balance']
        update_context(user_data, balance=new_balance)
    return undo_details

def format_undo_msg(details: dict, action_type):
    print(details)
    undo_details = "\n".join(
        f" → <b>{k}:</b> {details[k]}"
        for k in details
    )

    return "\n".join([
        "<b>Undo Complete</b>",
        f"The <b>{action_type}</b> command has been cancelled.",
        undo_details,
])