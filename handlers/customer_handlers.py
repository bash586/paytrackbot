# Customer-related Telegram handlers
from typing import Dict, List, Optional
from aiosqlite import Connection
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from utils.utils import (
    validate_selected_customer,
    get_args,
    format_transaction,
    format_summary_html
)
from handlers.context_manager import clear_conversation_ctx, get_selected_customer, set_selected_customer, update_context
from services.customer_service import (
    delete_customer,
    get_customer_summary,
    rename_customer,
    change_phone,
    get_customer_transactions,
)
from services.database_service import DatabaseManager
from services.customer_repository import CustomerRepository
from services.report_repository import ReportRepository
from utils.types import Customer
from config import (
    CANCEL_KEYBOARD,
    DATABASE_PATH,
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
    admin_id = update.effective_user.id
    summary = await get_customer_summary(customer_id, admin_id)
    if not summary:
        logger.error(f"Failed to fetch customer summary {customer_id}")
        await update.effective_message.reply_text("Something went wrong. Please try again later.")
        return
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
    await update.effective_message.delete()
    try:
        query_parts = query.data.split(":")
        if len(query_parts) < 2:
            logger.warning(f"Invalid selection format: {query.data}")
            await query.edit_message_text("Invalid selection format")
            return
        customer_id = int(query_parts[1])
    except (ValueError, IndexError) as exc:
        logger.error(f"Failed to parse customer selection: {exc}")
        await query.edit_message_text("Invalid selection format")
        return

    admin_id = update.effective_user.id
    from services.customer_service import get_customer
    selected_customer = await get_customer(customer_id, admin_id)
    is_valid, error_msg = validate_selected_customer(selected_customer)
    if not is_valid:
        logger.error(f"Customer validation failed: {error_msg} (customer_id={customer_id})")
        await query.edit_message_text("Customer not found or was deleted")
        return
    set_selected_customer(
            context.user_data,
            {k: selected_customer[k] for k in ("customer_id", "fullname", "balance")}
    )
    # Handle transaction report mode
    if len(query_parts) > 2:
        mode = query_parts[2]
        if mode == 'transactions_report':
            page = await get_customer_transactions(customer_id, admin_id, limit=5)
            if not page:
                logger.error(f"Failed to fetch transactions for customer {customer_id}")
                await query.edit_message_text("Unable to fetch transactions. Please try again.")
                return

            items: Optional[List[Customer]] = page['items']
            if not items:
                await query.edit_message_text("No Transactions Found.")
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

    # Handle addtransaction command
    feedback_msg = f"Selected <b>{selected_customer['fullname'].upper()}</b>\n{FEEDBACK_AVAILABLE_COMMANDS}"
    active_command = context.user_data.get('active_command')
    if active_command and active_command == 'addtransaction':
        args = context.user_data.get('active_command_args', '')
        if args and len(args) > 0:
            from services.customer_service import add_transaction
            res = await add_transaction(get_args(args), admin_id, customer_id, selected_customer['fullname'])
            if res['ok']:
                feedback = "\n".join(res['msg']) if len(res['msg']) > 0 else ""
                await update.effective_message.reply_text(text=feedback, parse_mode='HTML')
            else:
                feedback = "\n".join(res['msg']) if len(res['msg']) > 0 else ""
                await update.effective_message.reply_text(text="Failed to add new Transaction...\n" + feedback, parse_mode='HTML')
            clear_conversation_ctx(context.user_data)
            return
        await update.effective_message.reply_text(
            PROMPT_TRANSACTION_DETAILS, reply_markup=InlineKeyboardMarkup(CANCEL_KEYBOARD), parse_mode="HTML"
        )
        return RECEIVE_ARGS
    
    await update.effective_message.reply_html(feedback_msg)

async def delete_customer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a customer from the database."""
    selected_customer = get_selected_customer(context.user_data)
    if not selected_customer:
        logger.warning("Delete customer called without valid customer")
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return

    admin_id = update.effective_user.id
    customer_id = selected_customer['customer_id']
    customer_name = selected_customer['fullname']

    result = await delete_customer(customer_id, admin_id)
    if not result['ok']:
        logger.error(f"Failed to delete customer {customer_id}: {result['error']}")
        await update.effective_message.reply_text(f"Error: {result['error']}")
        return

    # Clear from context
    current_customer = get_selected_customer(context.user_data)
    if current_customer and current_customer["customer_id"] == customer_id:
        set_selected_customer(context.user_data, None)

    await update.effective_message.reply_text(f"Customer {customer_name} is deleted successfully")

async def rename_customer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rename a customer."""
    selected_customer = get_selected_customer(context.user_data)
    if not selected_customer:
        logger.debug("Rename customer called without valid customer")
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return

    args = get_args(update.effective_message.text)
    if len(args) == 0:
        logger.debug("Rename customer called without arguments")
        err_msg = INVALID_USAGE['rename']
        await update.effective_message.reply_html(err_msg)
        return

    customer_id = selected_customer['customer_id']
    admin_id = update.effective_user.id
    new_name = args[0]

    result = await rename_customer(new_name, customer_id, admin_id)
    if not result['ok']:
        logger.error(f"Failed to rename customer {customer_id}: {result['error']}")
        await update.effective_message.reply_text(result['error'])
        return

    # Update context with new name
    updated_customer = get_selected_customer(context.user_data)
    if updated_customer and updated_customer.get("customer_id") == customer_id:
        update_context(context.user_data, fullname=result['new name'])
    
    await update.effective_message.reply_text(f"Customer has been successfully renamed To:\n {result['new name'].upper()}")

async def change_phone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change a customer's phone number."""
    selected_customer = get_selected_customer(context.user_data)
    if not selected_customer:
        logger.warning("Change phone called without valid customer")
        await update.effective_message.reply_html(NO_SELECTED_CUSTOMER_WARNING)
        return
    
    args = get_args(update.effective_message.text)
    if len(args) == 0:
        logger.warning("Change phone called without arguments")
        err_msg = INVALID_USAGE['changephone']
        await update.effective_message.reply_html(err_msg)
        return
    
    new_phone = args[0]
    customer_id = selected_customer['customer_id']
    admin_id = update.effective_user.id
    
    result = await change_phone(new_phone, customer_id, admin_id)
    if not result['ok']:
        logger.error(f"Failed to change phone for customer {customer_id}: {result['error']}")
        await update.effective_message.reply_text(result['error'])
        return
    
    await update.effective_message.reply_text(f"Customer Phone Has Been Changed To:\n {result['proposed_phone'].upper()}")

