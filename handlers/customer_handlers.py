# Customer-related Telegram handlers
from typing import Dict, List, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from utils.utils import (
    validate_selected_customer,
    get_selected_customer,
    get_args,
    normalize_fullname,
    normalize_phone,
    normalize_name,
    update_context,
    reset_search_context,
    reset_command_context,
)
from utils.utils import format_transaction, format_summary_html
from services.customer_service import (
    select_customer,
    add_customer,
    delete_customer,
    rename_customer,
    change_phone,
)
from services.database_service import DatabaseManager
from services.customer_repository import CustomerRepository
from services.report_repository import ReportRepository
from utils.types import Customer
from config import (
    CANCEL_KEYBOARD,
    RECEIVE_ARGS,
    NO_SELECTED_CUSTOMER_WARNING,
    FEEDBACK_AVAILABLE_COMMANDS,
    PROMPT_TRANSACTION_DETAILS,
    INVALID_USAGE,
)
import logging

logger = logging.getLogger(__name__)

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get and display summary info about selected customer."""
    selected_customer = get_selected_customer(context.user_data)
    is_valid, error_msg = validate_selected_customer(selected_customer)
    if not is_valid:
        logger.warning(f"Summary called without valid customer: {error_msg}")
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return
    customer_id = selected_customer['customer_id']
    db_manager: DatabaseManager = context.bot_data['db_manager']
    admin_id = update.effective_user.id
    customer_repo = CustomerRepository(db_manager.conn)
    summary = await customer_repo.get_customer_summary(customer_id, admin_id)
    recent = summary['recent']
    recent_actions = []
    for i in range(len(recent)):
        item = recent[i]
        recent_actions.append(format_transaction(item, i == len(recent)-1))
    recent_actions_formatted = "".join(recent_actions) if len(recent_actions) > 0 else "No transactions found.\n"
    logger.info(f"payments {summary['payments']:.1f}")
    message = format_summary_html(summary, recent_actions_formatted)
    await update.effective_message.reply_html(text=message)

async def select_customer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle customer selection from callback query."""
    query = update.callback_query
    await query.answer()
    try:
        query_parts = query.data.split(":")
        if len(query_parts) < 2:
            await query.edit_message_text("Invalid selection format")
            return
        customer_id = int(query_parts[1])
    except (ValueError, IndexError) as exc:
        logger.error(f"Failed to parse customer selection: {exc}")
        await query.edit_message_text("Invalid selection format")
        return
    admin_id = update.effective_user.id
    db_manager: DatabaseManager = context.bot_data['db_manager']
    selected_customer = await select_customer(customer_id, admin_id, db_manager, context.user_data)
    is_valid, error_msg = validate_selected_customer(selected_customer)
    if not is_valid:
        logger.warning(f"Customer validation failed: {error_msg} (customer_id={customer_id})")
        await query.edit_message_text("Customer not found or was deleted")
        return
    if len(query_parts) > 2:
        mode = query_parts[2]
        if mode == 'transactions_report':
            report_repo = ReportRepository(db_manager.conn)
            page = await report_repo.fetch_transactions_page(customer_id, admin_id, 5)
            items: Optional[List[Customer]] = page['items']
            if not items:
                await query.edit_message_text("No Transactions Found.\n")
                return
            transactions_text = []
            for i, transaction in enumerate(items):
                transactions_text.append(format_transaction(transaction, i == len(items) - 1, include_details=True))
            transactions_formatted = "".join(transactions_text)
            message = f"「✦<b>{selected_customer['fullname'].upper()}</b>✦」\n\n{transactions_formatted}"
            buttons = []
            if page['has_more'] and page['next_cursor']:
                buttons.append([InlineKeyboardButton("→", callback_data=f"report:customer_transaction_history:{page['next_cursor']}:2:forwards")])
            buttons.append([InlineKeyboardButton("←", callback_data=f"report:main:0:0:backwards")])
            await query.edit_message_text(text=message, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
            return
    feedback_msg = f"Selected <b>{selected_customer['fullname'].upper()}</b>\n{FEEDBACK_AVAILABLE_COMMANDS}"
    active_command = context.user_data.get('active_command')
    if active_command and active_command == 'addtransaction':
        args = context.user_data.get('active_command_args','')
        if len(args) > 0:
            # Process stored args for transaction
            res = await add_transaction(get_args(args), update, context)
            if res['ok']:
                feedback = "\n".join(res['msg']) if len(res['msg']) > 0 else ""
                await update.effective_message.reply_text(text=feedback, parse_mode='HTML')
            else:
                feedback = "\n".join(res['msg']) if len(res['msg']) > 0 else ""
                await update.effective_message.reply_text(text="Failed to add new Transaction...\n" + feedback, parse_mode='HTML')
            reset_search_context(context.user_data)
            reset_command_context(context.user_data)
            return
        await update.effective_message.reply_text(PROMPT_TRANSACTION_DETAILS, reply_markup=CANCEL_KEYBOARD, parse_mode="HTML")
        return RECEIVE_ARGS
    await update.effective_message.reply_html(feedback_msg)

async def add_customer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a new customer to the database."""
    args = get_args(update.effective_message.text)
    if len(args) < 2:
        err_msg = INVALID_USAGE['addcustomer']
        await update.effective_message.reply_html(err_msg)
        return
    fullname, phone = normalize_fullname(args[0]), normalize_phone(args[1])
    admin_id = update.effective_user.id
    db_manager: DatabaseManager = context.bot_data['db_manager']
    result = await add_customer(fullname, phone, admin_id, db_manager, context.user_data, True)
    if not result['ok']:
        feedback = "\n".join(result['msg']) if len(result['msg']) > 0 else ""
        await update.effective_message.reply_html(f"Failed to add customer:\n{feedback}")
        return
    feedback_msg = "\n".join(result['msg']) if len(result['msg']) > 0 else ""
    await update.effective_message.reply_html(text=f"{feedback_msg}\n{FEEDBACK_AVAILABLE_COMMANDS}")

async def delete_customer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a customer from the database."""
    selected_customer = get_selected_customer(context.user_data)
    if not selected_customer:
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return
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

async def rename_customer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rename a customer."""
    selected_customer = get_selected_customer(context.user_data)
    if not selected_customer:
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return
    args = get_args(update.effective_message.text)
    if len(args) == 0:
        err_msg = INVALID_USAGE['rename']
        await update.effective_message.reply_html(err_msg)
        return
    customer_id = selected_customer['customer_id']
    admin_id = update.effective_user.id
    db_manager: DatabaseManager = context.bot_data['db_manager']
    new_name = args[0]
    result = await rename_customer(new_name, customer_id, admin_id, db_manager, context.user_data)
    new_name = result['new name']
    if not result['ok']:
        err_msg = result['error']
        await update.effective_message.reply_text(err_msg)
        return
    await update.effective_message.reply_text(f"Customer has been successfully renamed To:\n {new_name.upper()}")

async def change_phone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change a customer's phone number."""
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
    await update.effective_message.reply_text(f'Customer Phone Has Been Changed To:\n {new_phone.upper()}')


async def add_transaction_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a transaction for the selected customer."""
    selected_customer = get_selected_customer(context.user_data)
    if not selected_customer:
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return
    args = get_args(update.effective_message.text)
    description = "" if len(args)<2 else args[1]
    try:
        amount = float(normalize_name(args[0]))
        type_ = 'sale' if amount < 0 else 'payment'
        amount = abs(amount)
    except ValueError:
        await update.effective_message.reply_html("Invalid <b>amount</b> value: amount must be a number")
        return
    db_manager: DatabaseManager = context.bot_data['db_manager']
    admin_id = update.effective_user.id
    customer_id = selected_customer['customer_id']
    fullname = selected_customer['fullname']
    try:
        from services.transaction_repository import TransactionRepository
        trans_repo = TransactionRepository(db_manager.conn)
        await trans_repo.add_transaction(amount, type_, description, customer_id, admin_id)
    except Exception as exc:
        await update.effective_message.reply_text("Something went wrong. Please try again later.")
        return
    from services.customer_repository import CustomerRepository
    customer_repo = CustomerRepository(db_manager.conn)
    new_balance = (await customer_repo.get_customer_by_id(customer_id, admin_id))['balance']
    update_context(context.user_data, balance=new_balance)
    feedback_msg = '\n'.join([f"「 ✦<b>{fullname.upper()}</b>✦ 」", "  ─•────", f"Successfully added <b>{type_.upper()}</b> of <b>{amount:.2f}</b>", f"<b>Description: </b> {description}" if len(args)>2 else '', f"\n<b>Account Balance: {new_balance:.2f}</b>",])
    await update.effective_message.reply_html(feedback_msg)


async def add_transaction(args: List, update, context):
    """Process and add a transaction."""
    res = {'ok': True, 'msg': [], 'log_msg': []}
    description = "" if len(args) < 2 else args[1]
    try:
        amount = float(normalize_name(args[0]))
        type_ = 'sale' if amount < 0 else 'payment'
        amount = abs(amount)
    except ValueError:
        res["ok"] = False
        res["msg"].append("Invalid <b>amount</b> value: amount must be a number")
        return res
    
    db_manager: DatabaseManager = context.bot_data['db_manager']
    admin_id = update.effective_user.id
    selected_customer = get_selected_customer(context.user_data)
    customer_id = selected_customer['customer_id']
    fullname = selected_customer['fullname']
    amount = float(amount)
    res['log_msg'].append((f"adding a transaction for user with id :{admin_id}\n"
                          "passed arguments:\n"
                          f"amount:{amount}\n"
                          f"description:\n{description}"))
    try:
        from services.transaction_repository import TransactionRepository
        trans_repo = TransactionRepository(db_manager.conn)
        await trans_repo.add_transaction(amount, type_, description, customer_id, admin_id)
    except Exception as exc:
        res["ok"] = False
        res["msg"].append("Something went wrong. Please try again later.")
        res['log_msg'].append("error: " + str(exc))
        return res
    
    from services.customer_repository import CustomerRepository
    customer_repo = CustomerRepository(db_manager.conn)
    new_balance = (await customer_repo.get_customer_by_id(customer_id, admin_id))['balance']
    update_context(context.user_data, balance=new_balance)
    desc = f"<b>Description: </b> {description}" if len(args) > 1 else ''
    feedback_msg = (f"「 ✦<b>{fullname.upper()}</b>✦ 」\n"
                    "  ─•────\n"
                    f"Successfully added <b>{type_.upper()}</b> of <b>{amount:.2f}</b>\n"
                    f"{desc}"
                    f"\n<b>Account Balance: {new_balance:.2f}</b>")
    res["msg"].append(feedback_msg)
    return res
