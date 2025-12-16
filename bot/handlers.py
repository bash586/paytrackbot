from functools import reduce
import json
from typing import Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from bot.helpers import is_valid_name, normalize_fullname, is_valid_phone, get_args, normalize_name, normalize_phone
from bot.database_manager import DatabaseManager, AppError
from config import INVALID_USAGE, NO_SELECTED_CUSTOMER_WARNING,WELCOME_MSG
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# General handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_message:
        await update.effective_message.reply_html(WELCOME_MSG)

async def update_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """update history of commands made by admin"""

# Customer handlers
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    command syntax:
        /search query*|[limit: Default 5]
    """

    # validate inputs
    msg_txt = update.effective_message.text
    args = ['']
    if not msg_txt.strip() == '/search':
        args = get_args(msg_txt)

    if not args:
        await update.effective_message.reply_text("Usage: /search query*|limit")
        return

    query = args[0]
    limit = 5 if len(args) < 2 else int(args[1])

    # execute sql query
    db_manager: DatabaseManager = context.bot_data['db_manager']
    admin_id = update.effective_user.id
    customers = await db_manager.search_customers(query, limit, admin_id)
    if not customers:
        await update.effective_message.reply_text("No customers found")
        return

    # Show each search result as a user-selectable option.
    keyboard = [
        [InlineKeyboardButton(customer["fullname"].upper(), callback_data=f"customer_select:{customer["id"]}")]
        for customer in customers
    ]

    await update.effective_message.reply_text(text='Choose One Customer:', reply_markup=InlineKeyboardMarkup(keyboard))

async def select_customer(customer_id, admin_id, db_manager, user_data):

    # Fetch customer from database
    customer = await db_manager.get_customer_by_id(customer_id, admin_id)
    if not customer:
        return None

    # update user_data
    set_selected_customer(
        user_data,
        {k: customer[k] for k in ("customer_id", "fullname", "balance")}
    )
    return customer

async def select_customer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    customer_id = int(query.data.split(":", maxsplit=1)[1])
    admin_id = update.effective_user.id
    db_manager: DatabaseManager = context.bot_data['db_manager']

    selected_customer = await select_customer(customer_id, admin_id, db_manager, context.user_data)

    if not selected_customer:
        logger.warning("Selected Customer can not be Found")
        await query.edit_message_text("Customer not found or was deleted")
        return

    # Feedback message
    feedback_msg = '\n'.join([
        f"Selected <b>{selected_customer['fullname'].upper()}</b>...",
        "Now, you can... ",
        "- to view customer's info, use command:",
        "   <code>/summary</code>",
        "- to add transactions, use command:",
        "   <code>/addtransaction amount*|type*|info</code>",
    ])
    await query.delete_message()
    await update.effective_message.reply_html(feedback_msg)

async def add_customer(
    fullname, phone, admin_id, db_manager: DatabaseManager, user_data, with_logging,
    customer_id=None, created_at=None, balance=None
):
    fullname, phone = normalize_fullname(fullname), normalize_phone(phone)

    # validate inputs
    if not is_valid_name(fullname):
        err_msg = """
        Invalid Name: name should include:
        - first and last name (required)
        - middle name (optional)
        """
        return {
            'ok': False,
            'error': err_msg
        }

    if not is_valid_phone(phone):
        err_msg = "Invalid Phone Number"
        return {
            'ok': False,
            'error': err_msg
        }

    try:
        old_info = {
            'customer_id': customer_id,
            'created_at': created_at,
            'balance': balance
        } if not with_logging else None
        result = await db_manager.add_customer(fullname, phone, admin_id, with_logging, old_info)
        customer_id = result['customer_id']

    except AppError as exc:
        return {
            'ok': False,
            'error': str(exc)
        }
    except Exception as exc:
        return {
            'ok': False,
            'error': "Something went wrong. Please try again later."
        }

    # select added customer
    if with_logging:
        await select_customer(customer_id, admin_id, db_manager, user_data)
    undo_details = result['undo_details']
    return {
        'ok': True,
        'error': None,
        'undo_details': undo_details,
        'action_type': 'delete-customer'
    }
async def add_customer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Usage: /addcustomer <fullname>|<phone number>

    args = get_args(update.effective_message.text)

    if len(args) < 2:
        err_msg = INVALID_USAGE['addcustomer']
        return await update.effective_message.reply_html(err_msg)

    fullname, phone = normalize_fullname(args[0]), normalize_phone(args[1])

    admin_id = update.effective_user.id
    db_manager: DatabaseManager = context.bot_data['db_manager']

    result = await add_customer(fullname, phone, admin_id, db_manager, context.user_data, True)
    if not result['ok']:
        await update.effective_message.reply_text(result['error'])
        return

    await update.effective_message.reply_text(f'New Customer: added {fullname.upper()}')

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """get more info about selected customer"""
    # context validation
    selected_customer = get_selected_customer(context.user_data)
    if not selected_customer:
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return
    customer_id = selected_customer['customer_id']

    db_manager: DatabaseManager = context.bot_data['db_manager']
    admin_id = update.effective_user.id

    summary = await db_manager.get_customer_summary(customer_id, admin_id)

    recent = summary['recent']
    recent_actions = []

    def format_transaction(transaction, is_last):
        return "\n".join([
            f"<b>{'💸' if transaction['type'] == 'sale' else '💰'} {transaction['amount']:.1f}</b>",
            f"                  {transaction['created_at']}",
            '  ────୨ৎ────' if not is_last 
            else '────୨ৎ────\n\n   【 💸 = sale │ 💰 = payment 】 \n ',
            ' '
        ])

    for i in range(len(recent)):
        item = recent[i]
        recent_actions.append(format_transaction(item, i == len(recent)-1))
    recent_actions_formatted = "".join(recent_actions) if len(recent_actions)>0 else "No transactions found."
    logger.info(f'payments {summary['payments']:.1f}')

    await update.effective_message.reply_html(text=f"""
<b>「✦{summary['fullname'].upper()}✦」</b>
  ─•────
Phone: <b><code>{summary['phone']}</code></b>

Total Payments: <b>{summary['payments']:.1f}</b>
Total Sales: <b>{summary['sales']:.1f}</b>
Balance: <b>{summary['balance']:.1f}</b>

Recent Transactions:
<blockquote>
{recent_actions_formatted}
</blockquote>
    """)

# Transaction handlers
async def add_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Usage: /addtransaction <amount>|<type>|[description]

    # context validation
    selected_customer = get_selected_customer(context.user_data)
    if not selected_customer:
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return

    # syntax validation
    args = get_args(update.effective_message.text)
    if len(args) == 0:
        err_msg = INVALID_USAGE['addtransaction']
        await update.effective_message.reply_html(err_msg)
        return

    type_ = normalize_name(args[1])
    description = "" if len(args)<3 else args[2]
    try:
        amount = float(normalize_name(args[0]))
    except ValueError:
        await update.effective_message.reply_html("Invalid <b>amount</b> value: amount must be a number")
        return

    if not type_ in ('sale', 'payment'):
        err_msg = INVALID_USAGE['addtransaction']
        await update.effective_message.reply_html(err_msg)
        return

    if amount <= 0:
        await update.effective_message.reply_html("<b>Only positive amounts are allowed...</b>")
        return

    db_manager: DatabaseManager = context.bot_data['db_manager']
    admin_id = update.effective_user.id

    customer_id = selected_customer['customer_id']
    fullname = selected_customer['fullname']

    amount = float(amount)
    try:
        transaction = await db_manager.add_transaction(amount, type_, description, customer_id, admin_id)
    except Exception as exc:
        await update.effective_message.reply_text("Something went wrong. Please try again later.")
        return
    selected_customer['balance'] = (await db_manager.get_customer_by_id(customer_id, admin_id))['balance']
    new_balance = selected_customer['balance']


    feedback_msg = '\n'.join([
            f"「 ✦<b>{fullname.upper()}</b>✦ 」",
            "  ─•────",
            f"Successfully added <b>{type_.upper()}</b> of <b>{amount:.2f}</b>",
            f"<b>Description: </b> {description}" if len(args)>2 else '',
            f"\n<b>Account Balance: {new_balance:.2f}</b>",
    ])

    await update.effective_message.reply_html(feedback_msg)
    


async def delete_transaction(
    customer_id: int, admin_id: int, id: int,
    db_manager:DatabaseManager, user_data: dict, with_logging = True
):
    details = await db_manager.delete_transaction(id)
    return {
        'action_type': 'record-transaction',
        'undo_details': {
            'Full Name': details['fullname'].upper(),
            'Amount': details['amount'],
            'Type': details['type'],
            'Description': details['description'] if len(details['description'])>0 else '-',
            'Current Balance': details['balance'],
        }
    }

async def delete_customer(
    customer_id: int, admin_id: int,
    db_manager: DatabaseManager,
    user_data: dict,
    with_logging=True,
):

    try:
        deleted_customer = await db_manager.delete_customer(customer_id, admin_id, with_logging)
    except AppError:
        return {
            'ok': False,
            'error': f"{str(exc)}",
        }
    except Exception as exc:
        return {
            'ok': False,
            'error': "Something went wrong. Please try again later.",
        }

    # remove customer from context
    selected_customer = get_selected_customer(user_data)
    if selected_customer and selected_customer['customer_id'] == customer_id:
        set_selected_customer(user_data, None)

    return {
        'ok': True,
        'error': None,
        'undo_details': {
            'Full Name': deleted_customer['fullname'].upper(),
            'Phone': deleted_customer['phone'],
            'balance': deleted_customer['balance'],
        },
        'action_type': 'add-customer'
    }

async def delete_customer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # get selected customer
    selected_customer = get_selected_customer(context.user_data)
    if not selected_customer:
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return

    # delete customer from database
    db_manager: DatabaseManager = context.bot_data['db_manager']

    admin_id = update.effective_user.id
    customer_id = selected_customer['customer_id']
    customer_name = selected_customer['fullname']

    result = await delete_customer(customer_id, admin_id, db_manager, context.user_data)
    if not result['ok']:
        msg_err = result['error']
        if msg_err.startswith('Error:'):
            await update.effective_message.reply_text(f"Error: {msg_err}")
        elif msg_err.startswith('Unknown Error:'):
            await update.effective_message.reply_text(f"Error: Customer is not Deleted... retry later")
        return

    await update.effective_message.reply_text(f"Customer {customer_name} is deleted successfully")

async def rename_customer(
    new_name: str, 
    customer_id: int,
    admin_id: int,
    db_manager: DatabaseManager,
    user_data: dict,
    with_logging=True,
):
    new_name = normalize_fullname(new_name)
    if not is_valid_name(new_name):
        return {
            'ok': False,
            'error': """
                Invalid Name: name should include:
                - first and last name (required)
                - middle name (optional)
            """,
            'new name': new_name,
        }

    try:
        old_name = await db_manager.rename_customer(new_name, customer_id, admin_id, with_logging)
    except AppError as exc:
        return {
            'ok': False,
            'error': str(exc),
            'new name': new_name,
        }
    except Exception as exc:
        return {
            'ok': False,
            'error': "Something went wrong. Please try again later.",
            'new name': new_name,
        }


    # update context
    selected_customer = get_selected_customer(user_data)
    if selected_customer['customer_id'] == customer_id:
        rename_customer_state(user_data, new_name)
    undo_dict = {
        'Current Name': new_name,
        'Was Renamed To': old_name,
    }

    return {
        'ok': True,
        'error': None,
        'new name': new_name,
        'undo_details': undo_dict,
        'action_type': 'rename-customer'
    }

async def rename_customer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # get selected customer
    selected_customer = get_selected_customer(context.user_data)
    if not selected_customer:
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return

    args = get_args(update.effective_message.text)
    if len(args) == 0:
        err_msg = INVALID_USAGE['renamecustomer']
        await update.effective_message.reply_html(err_msg)
        return

    customer_id = selected_customer['customer_id']
    admin_id = update.effective_user.id

    # update database
    db_manager: DatabaseManager = context.bot_data['db_manager']
    new_name = args[0]
    result = await rename_customer(new_name, customer_id, admin_id, db_manager, context.user_data)
    new_name = result['new name']

    if not result['ok']:
        err_msg = result['error']
        await update.effective_message.reply_text(err_msg)
        return

    # feedback
    await update.effective_message.reply_text(f"""
        Customer has been successfully renamed To:\n {new_name.upper()}
    """)

async def change_phone(
    new_phone, customer_id, admin_id, 
    db_manager,
    user_data: dict,
    with_logging=True,
):
    new_phone = normalize_phone(new_phone)
    if not is_valid_phone(new_phone):
        return {
            'ok': False,
            'error': f"Invalid phone number: {new_phone}",
            'proposed_phone': new_phone,
        }

    try:
        result = await db_manager.change_customer_phone(new_phone, customer_id, admin_id, with_logging)
    except AppError as exc:
        return{
            'ok': False,
            'error': str(exc),
            'proposed_phone': new_phone,
        }
    except Exception as exc:
        return {
            'ok': False,
            'error': "Something went wrong. Please try again later.",
            'proposed_phone': new_phone,
        }

    return {
        'ok': True,
        'error': None,
        'proposed_phone': new_phone,
        'undo_details': {
            'Full Name': result['fullname'],
            'Current Phone': new_phone,
            'Phone Was Changed To': result['old_phone'],
        },
        'action_type': 'update-phone'
    }

async def change_phone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # get selected customer
    selected_customer = get_selected_customer(context.user_data)
    if not selected_customer:
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return

    args = get_args(update.effective_message.text)
    if len(args) == 0:
        err_msg = INVALID_USAGE['changephone']
        await update.effective_message.reply_html(err_msg)
        return

    new_phone = args[0]

    customer_id = selected_customer['customer_id']
    admin_id = update.effective_user.id

    db_manager: DatabaseManager = context.bot_data['db_manager']

    result = await change_phone(new_phone, customer_id, admin_id, db_manager, context.user_data, True)
    if not result['ok']:
        err_msg = result['error']
        await update.effective_message.reply_text(err_msg)
        return

    # feedback
    await update.effective_message.reply_text(
        f'Customer Name Has Been Changed To:\n {new_phone.upper()}'
    )

async def undo_last_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inverse = {
        "rename_customer": rename_customer,
        "change_phone": change_phone,
        "delete_customer": add_customer,
        "add_customer": delete_customer,
        "add_transaction": delete_transaction,
    }
    kwargs = dict()
    # fetch last action log
    db_manager: DatabaseManager = context.bot_data['db_manager']
    admin_id = update.effective_sender.id
    action_log = await db_manager.undo_last_action(admin_id)
    action_type = action_log['action_type']

    payload = json.loads(action_log['payload'])
    customer_transactions = payload.pop('customer_transactions', None)
    customer_id = action_log['customer_id']

    inverse_func = inverse[action_type]
    kwargs.update({
        "db_manager": db_manager,
        "user_data": context.user_data,
        "customer_id":customer_id,
        "admin_id":admin_id,
        "with_logging": False,
    })
    kwargs.update(payload)

    result = await inverse_func(**kwargs)
    
    if customer_transactions:
        await db_manager.restore_transactions(customer_transactions)

    details = result['undo_details']
    action_type = result['action_type']
    await update.effective_message.reply_html(format_undo_msg(details, action_type))


# managing context state
def get_selected_customer(user_data: dict)->Optional[dict]:
    context_state = user_data.get("context_state", {})
    selected_customer = context_state.get("selected_customer", None)
    return selected_customer

def set_selected_customer(user_data: dict, selected_customer=None)->None:
    context_state = user_data.setdefault('context_state', {})
    context_state['selected_customer'] = selected_customer

def rename_customer_state(user_data: dict, new_name: str)->None:
    context_state = user_data['context_state']
    customer = context_state['selected_customer']
    customer['fullname'] = new_name
    
def format_undo_msg(details: dict, action_type):
    undo_details = "\n".join(
        f" → <b>{k}:</b> {details[k]}"
        for k in details
    )

    return "\n".join([
        "<b>Undo Complete</b>",
        f"The <b>{action_type}</b> command has been cancelled.",
        undo_details
    ])