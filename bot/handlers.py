from datetime import datetime
import json
from typing import Optional
from aiosqlite import IntegrityError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from bot.helpers import is_valid_name, normalize_fullname, is_valid_phone, get_args, normalize_name, normalize_phone
from bot.database_manager import DatabaseManager
from config import DATABASE_PATH, NO_SELECTED_CUSTOMER_WARNING,welcome_msg
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# General handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_message:
        await update.effective_message.reply_html(welcome_msg)

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
        {k: customer[k] for k in ("id", "fullname", "balance")}
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

async def add_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Usage: /addcustomer <fullname>|<phone number>

    args = get_args(update.effective_message.text)

    if len(args) < 2:
        err_msg = '\n'.join([
            f"<b>Incorrect Command Usage...</b>",
            "Usage: <code>/addcustomer fullname*|phone*</code>"
        ])
        return await update.effective_message.reply_html(err_msg)

    fullname, phone = normalize_fullname(args[0]), normalize_phone(args[1])

    # validate inputs
    if not is_valid_name(fullname):
        await update.effective_message.reply_text("""
        Invalid Name: name should include:
        - first and last name (required)
        - middle name (optional)
        """)
        return

    if not is_valid_phone(phone):
        await update.effective_message.reply_text(f"Invalid Phone Number")
        return

    # add to database
    db_manager: DatabaseManager = context.bot_data['db_manager']
    admin_id = update.effective_user.id

    try:
        customer_row = await db_manager.add_customer(fullname, phone, admin_id)
    except IntegrityError as exc:
        await update.effective_message.reply_text(f"Customer with name {fullname.upper()} already exists")
        return
    except Exception as exc:
        await update.effective_message.reply_text(f"Error: {str(exc)}")
        return

    customer_id = customer_row['id']
    await update.effective_message.reply_text(f'New Customer: added {fullname.upper()}')
    # select added customer
    await select_customer(customer_id, admin_id, db_manager, context.user_data)

    # bookmark: log action
    action_info = dict()
    try:
        await db_manager.add_action_log('add_customer', customer_id, admin_id, action_info)
    except Exception as exc:
        await update.effective_message.reply_text(f"Action failed to get logged: {str(exc)}")
        return

    # bookmark: check all existing names if there is similarities in first\last name

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """get more info about selected customer"""
    # context validation
    selected_customer = get_selected_customer(context.user_data)
    if not selected_customer:
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return
    customer_id = selected_customer['id']

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
        err_msg = '\n'.join([
            "<b>Incorrect Command Usage...</b>",
            "Usage: <code>/addtransaction amount*|type*|info</code>",
            "type*: '<b>sale</b>' or '<b>payment</b>' ",
        ])
        await update.effective_message.reply_html(err_msg)
        return

    amount = normalize_name(args[0])
    type_ = normalize_name(args[1])
    description = "" if len(args)<3 else args[2]

    if not amount.isdigit() or not type_ in ('sale', 'payment'):
        err_msg = '\n'.join([
            "<b>Incorrect Command Usage...</b>",
            "Usage: <code>/addtransaction amount*|type*|info</code>",
            "type*: '<b>sale</b>' or '<b>payment</b>' ",
        ])
        await update.effective_message.reply_html(err_msg)
        return

    if float(amount) <= 0:
        err_msg = '\n'.join([
            "<b>Only positive amounts are allowed...</b>",
        ])
        await update.effective_message.reply_html(err_msg)
        return

    db_manager: DatabaseManager = context.bot_data['db_manager']
    admin_id = update.effective_user.id

    customer_id = selected_customer['id']
    fullname = selected_customer['fullname']

    amount = float(amount)
    selected_customer['balance'] += (1 if type_ == 'payment' else -1) * amount
    new_balance = selected_customer['balance']
    try:
        transaction = await db_manager.add_transaction(amount, type_, description, customer_id, admin_id)
    except Exception as exc:
        await update.effective_message.reply_text(f"Error: {str(exc)}")
        return


    feedback_msg = '\n'.join([
            f"「 ✦<b>{fullname.upper()}</b>✦ 」",
            "  ─•────",
            f"Successfully added <b>{type_.upper()}</b> of <b>{amount:.2f}</b>",
            f"<b>Description: </b> {description}" if len(args)>2 else '',
            f"\n<b>Account Balance: {new_balance:.2f}</b>",
    ])

    await update.effective_message.reply_html(feedback_msg)

    # log action

    action_info = dict(transaction)
    try:
        await db_manager.add_action_log('add_transaction', customer_id, admin_id, action_info)
    except Exception as exc:
        await update.effective_message.reply_text(f"Error: {str(exc)}")
        return

async def delete_customer(
    customer_id: int, admin_id: int,
    db_manager: DatabaseManager,
    user_data: dict,
    with_logging=True,
):

    try:
        is_deleted = await db_manager.delete_customer(customer_id, admin_id, with_logging)
    except Exception as exc:
        return {
            'ok': False,
            'error': f"Error: {str(exc)}",
        }

    if not is_deleted:
        return {
            'ok': False,
            'error': "Unknown Error: Customer can not be deleted now... retry later"
        }

    # remove customer from context
    selected_customer = get_selected_customer(user_data)
    if selected_customer['id'] == customer_id:
        set_selected_customer(user_data, None) 

    return {
        'ok': True,
        'error': None
    }

async def delete_customer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Usage: /deletecustomer

    # get selected customer
    selected_customer = get_selected_customer(context.user_data)
    if not selected_customer:
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return

    # delete customer from database
    db_manager: DatabaseManager = context.bot_data['db_manager']

    admin_id = update.effective_user.id
    customer_id = selected_customer['id']
    customer_name = select_customer['fullname']

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
            'proposed_name': new_name,
        }

    try:
        is_renamed = await db_manager.rename_customer(new_name, customer_id, admin_id, with_logging)
    except IntegrityError:
        return {
            'ok': False,
            'error': f"IntegrityError: Customer with name: {new_name} already exists",
            'proposed_name': new_name,
        }
    except Exception as exc:
        return {
            'ok': False,
            'error': f"Error: {str(exc)}",
            'proposed_name': new_name,
        }

    if not is_renamed:
        return {
            'ok': False,
            'error': "Unknown Error: Customer can not be renamed now... retry later",
            'proposed_name': new_name,
        }

    # update context
    selected_customer = get_selected_customer(user_data)
    if selected_customer['id'] == customer_id:
        rename_customer_state(user_data, new_name)

    return {
        'ok': True,
        'error': None,
        'proposed_name': new_name,
    }

async def rename_customer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # get selected customer
    selected_customer = get_selected_customer(context.user_data)
    if not selected_customer:
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return

    args = get_args(update.effective_message.text)
    if len(args) == 0:
        err_msg = '\n'.join([
            "<b>Incorrect Command Usage...</b>",
            "Usage: <code>/renamecustomer newname*</code>",
        ])
        await update.effective_message.reply_html(err_msg)
        return

    customer_id = selected_customer['id']
    admin_id = update.effective_user.id

    # update database
    db_manager: DatabaseManager = context.bot_data['db_manager']
    new_name = args[0]
    result = await rename_customer(new_name, customer_id, admin_id, db_manager, context.user_data)
    new_name = result['proposed_name']

    if not result['ok']:
        err_msg = result['error']
        if err_msg.startswith('IntegrityError'):
            await update.effective_message.reply_text(f"Customer with name {result['proposed_name'].upper()} already exists")
        else:
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
        is_updated = await db_manager.change_customer_phone(new_phone, customer_id, admin_id, with_logging)
    except Exception as exc:
        return {
            'ok': False,
            'error': f"Error: {str(exc)}",
            'proposed_phone': new_phone,
        }

    if not is_updated:
        return {
            'ok': False,
            'error': "Unknown Error: Customer phone is not updated... retry later",
            'proposed_phone': new_phone,
        }

    return {
        'ok': True,
        'error': None,
        'proposed_phone': new_phone,
    }

async def change_phone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # get selected customer
    selected_customer = get_selected_customer(context.user_data)
    if not selected_customer:
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return

    args = get_args(update.effective_message.text)
    if len(args) == 0:
        err_msg = '\n'.join([
            "<b>Incorrect Command Usage...</b>",
            "Usage: <code>/changephone newphone*</code>",
        ])
        await update.effective_message.reply_html(err_msg)
        return

    new_phone = args[0]

    customer_id = selected_customer['id']
    admin_id = update.effective_user.id

    db_manager: DatabaseManager = context.bot_data['db_manager']

    result = await change_phone(new_phone, customer_id, admin_id, db_manager, context.user_data, True)
    if not result['ok']:
        err_msg = result['error']
        await update.effective_message.reply_text(err_msg)
        return

    # feedback
    await update.effective_message.reply_text(f"Customer Phone has been successfully updated To:\n {result['proposed_phone']}")

    # feedback
    await update.effective_message.reply_text(
        f'Customer Name Has Been Changed To:\n {new_phone.upper()}'
    )

async def undo_last_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_manager = context.bot_data['db_manager']
    # delete and fetch last action log
    action_log = await db_manager.undo_last_action()
    # decide which inverse function to execute
    action_type = action_log['action_type']
    logging_info = json.loads(action_log['payload'])
    customer_id = action_log['customer_id']
    admin_id = action_log['admin_id']

    match action_type:
        case 'rename_customer':
            result = await rename_customer(
                logging_info['old_name'], customer_id, admin_id, db_manager,
                context.user_data, with_logging=False,
            )
        case 'change_phone':
            result = await change_phone(
                logging_info['old_phone'], customer_id, admin_id, db_manager,
                context.user_data, with_logging=False,
            )

        case 'delete_customer ':
            result = await add_customer(
                logging_info['old_phone'], customer_id, admin_id, db_manager,
                context.user_data, with_logging=False,
            )
    # cancel action by executing corresponding inverse function

def view_latest_transactions():
    pass

def merge_accounts():
    pass

def link_accounts():
    pass

# utils


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
    