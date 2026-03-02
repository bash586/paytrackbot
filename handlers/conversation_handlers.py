# Conversation state machine handlers
from typing import Dict
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler
from services.customer_service import get_customer as select_customer
from utils.utils import (
    get_args,
)
from handlers.context_manager import get_selected_customer, clear_conversation_ctx, update_context
from services.database_service import DatabaseManager
from utils.types import ReportView
from config import (
    DATABASE_PATH,
    WELCOME_MSG,
    RECEIVE_ARGS,
    RECEIVE_QUERY,
    ASK_QUERY,
    PROMPT_CUSTOMER_SEARCH,
    CANCEL_KEYBOARD,
    ALLOWED_COMMANDS,
    ALLOWED_SEARCH_MODES,
)
from services.customer_service import add_transaction
from handlers.report_handlers import init_report_ctx, get_search_results
import logging
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if update.effective_message:
        await update.effective_message.reply_html(WELCOME_MSG)

async def ask_command_args(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process command invocation and route to appropriate handler."""
    # start with a clean state
    clear_conversation_ctx(context.user_data)
    
    user_input = update.effective_message.text.strip()
    if not user_input:
        logger.warning("Empty command input")
        await update.effective_message.reply_html("Invalid command format")
        return ConversationHandler.END
    parts = user_input.split(maxsplit=1)
    mode = parts[0][1:]
    args = parts[1] if len(parts) > 1 else ""

    if mode not in ALLOWED_COMMANDS:
        logger.warning(f"Unknown command: {mode}")
        await update.effective_message.reply_html(f"Unknown command: /{mode}")
        clear_conversation_ctx(context.user_data)
        return ConversationHandler.END

    context.user_data["active_command"] = mode
    prompt = None # feedback msg
    match mode:
        case "addtransaction":
            selected_customer = get_selected_customer(context.user_data)
            if args:
                context.user_data["active_command_args"] = args
                if selected_customer: # execute command directly
                    return await receive_command_args(update, context)
            if not selected_customer:
                return await ask_search_query(update, context)
            from config import PROMPT_TRANSACTION_DETAILS
            fullname = selected_customer['fullname']
            prompt = PROMPT_TRANSACTION_DETAILS.format(customer_fullname = fullname)

        case "addcustomer":
            if args: # execute command directly
                context.user_data["active_command_args"] = args
                return await receive_command_args(update, context)

            from config import PROMPT_NEW_CUSTOMER_INFO
            prompt = PROMPT_NEW_CUSTOMER_INFO

    await update.effective_message.reply_text(
        prompt, 
        reply_markup=InlineKeyboardMarkup(CANCEL_KEYBOARD),
        parse_mode="HTML"
    )
    return RECEIVE_ARGS

async def receive_command_args(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process command arguments after user input."""
    active_command = context.user_data.get("active_command")
    if not active_command or active_command not in ALLOWED_COMMANDS:
        logger.error(f"Invalid active_command: {active_command}")
        await update.effective_message.reply_text("Invalid command state")
        # Cleanup and end conversation
        clear_conversation_ctx(context.user_data)
        return ConversationHandler.END

    admin_id = update.effective_user.id
    args = get_args(context.user_data.get('active_command_args', ''))
    if not args:
        args = get_args(update.message.text)
    if not args:
        logger.warning(f"No arguments provided for command: {active_command}")
        await update.effective_message.reply_text(text="No arguments provided. Please enter transaction details.", reply_markup=InlineKeyboardMarkup(CANCEL_KEYBOARD), parse_mode='HTML')
        return RECEIVE_ARGS

    match active_command:
        case "addtransaction":
            selected_customer = get_selected_customer(context.user_data)
            res: Dict = await add_transaction(
                args, admin_id,
                selected_customer['customer_id'], selected_customer['fullname']
            )
            next_state = await handle_service_result(
                update, res, fail_return=RECEIVE_ARGS,
                fail_markup=InlineKeyboardMarkup(CANCEL_KEYBOARD),
                fail_msg_intro="Failed to add new Transaction...\n",
            )
            if not res['ok']:
                return next_state
            new_balance = res['data']['new_balance']
            update_context(context.user_data, balance=new_balance)

        case "addcustomer":
            from services.customer_service import add_customer
            res: Dict = await add_customer(args, admin_id)
            next_state = await handle_service_result(
                update, res, fail_return=RECEIVE_ARGS,
                fail_markup=InlineKeyboardMarkup(CANCEL_KEYBOARD),
                fail_msg_intro="Failed to add new Customer...\n",
            )
            if not res['ok']:
                return next_state
            customer_id = res.get('customer_id')
            customer_to_select = await select_customer(customer_id, admin_id)
            if customer_to_select:
                from handlers.context_manager import set_selected_customer
                set_selected_customer(
                    context.user_data,
                    {k: customer_to_select[k] for k in ("customer_id", "fullname", "balance")}
                )

    # cleanup and end conversation
    logger.info(f"User {update.effective_user.id} completed conversation successfully")
    clear_conversation_ctx(context.user_data)
    return ConversationHandler.END

async def ask_search_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiate customer search in specified mode."""
    query = update.callback_query
    if not query:
        context.user_data["search_mode"] = "default"
        await update.effective_message.reply_text(PROMPT_CUSTOMER_SEARCH, reply_markup=InlineKeyboardMarkup(CANCEL_KEYBOARD), parse_mode="HTML")
        return RECEIVE_QUERY
    await query.answer()
    parts = query.data.split(":")
    if len(parts) < 2:
        logger.warning(f"Invalid search query callback format: {query.data}")
        await query.edit_message_text("Invalid search mode")
        # Cleanup and end conversation on error
        clear_conversation_ctx(context.user_data)
        return ConversationHandler.END
    mode = parts[1]
    if mode not in ALLOWED_SEARCH_MODES:
        logger.warning(f"Invalid search mode in callback: {mode}")
        await query.edit_message_text("Invalid search mode")
        # Cleanup and end conversation on error
        clear_conversation_ctx(context.user_data)
        return ConversationHandler.END
    context.user_data["search_mode"] = mode
    msg_id = update.effective_message.id
    if mode == "transactions_report":
        report_navigator = context.user_data.get('report_navigator')
        if (report_navigator is None or (report_navigator['mode'] != ReportView.CUSTOMER_TRANSACTION_HISTORY or report_navigator['msg_id'] != msg_id)):
            report_navigator = init_report_ctx(context.user_data, ReportView.CUSTOMER_TRANSACTION_HISTORY, msg_id, 1)
    await query.edit_message_text("To proceed, please <b>enter a customer Name/Phone...</b>", reply_markup=InlineKeyboardMarkup(CANCEL_KEYBOARD), parse_mode='HTML')
    return RECEIVE_QUERY

async def receive_search_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process customer search query and display results."""
    admin_id = update.effective_user.id
    args = get_args(update.message.text)
    search_query = args[0]
    limit = args[1] if len(args) > 1 else 5
    search_mode = context.user_data["search_mode"]
    keyboard = await get_search_results(search_query, limit, admin_id, search_mode)
    if search_mode == "default":
        if not keyboard:
            await update.effective_message.reply_text(text=(f"No customers found with name: <b>{search_query}</b>.\n\n" "Please enter another customer name\n"), reply_markup=CANCEL_KEYBOARD, parse_mode='HTML')
            return ASK_QUERY
        await update.effective_message.reply_text(text='Choose One Customer:', reply_markup=InlineKeyboardMarkup(keyboard),)
    elif search_mode == "transactions_report":
        msg_id = context.user_data.get("report_navigator",dict()).get('msg_id')
        await update.effective_message.delete()
        if not keyboard:
            reply_keyboard = [[InlineKeyboardButton(text="Home", callback_data="report:main:0:0:forwards",)]]
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg_id, text=(f"No customers found with name: <b>{search_query}</b>.\n\n" "Please enter another customer name\n"), reply_markup=InlineKeyboardMarkup(reply_keyboard), parse_mode='HTML')
            return ASK_QUERY
        await update.message.reply_text(
            text=("To Proceed, Select one Customer:\n\n"),
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
        )
    if context.user_data.get('active_command'):
        return RECEIVE_ARGS

    # Conversation complete - cleanup and end
    clear_conversation_ctx(context.user_data)
    logger.info(f"User {update.effective_user.id} completed conversation successfully")
    return ConversationHandler.END

async def end_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    General handler to end a conversation.
    Triggered by:
    - Cancel button clicks (callback_data="end_conversation")
    """
    # Clean up all user context data
    clear_conversation_ctx(context.user_data)

    # Identify what triggered the end
    if update.callback_query:
        query = update.callback_query
        await query.answer("Conversation cancelled")
        await query.delete_message()
        logger.info(f"User {update.effective_user.id} cancelled conversation via cancel button")

    return ConversationHandler.END

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /undo command to revert the last action."""
    admin_id = update.effective_user.id
    from services.undo_service import undo_service
    res = await undo_service(admin_id)
    await handle_service_result(update, res, fail_msg_intro= "Failed to Undo...\n")
    if not res['ok']:
        return
    data = res['data']
    action_type = data['action_type']
    match action_type:
        case "add_customer":
            customer_id = data['customer_id']
            selected_customer = get_selected_customer(context.user_data)
            # if deleted customer is stored in context, remove it!
            if selected_customer and selected_customer['customer_id'] == customer_id:
                from handlers.context_manager import set_selected_customer
                set_selected_customer(context.user_data, None)
        case "add_transaction":
            db = DatabaseManager(DATABASE_PATH)
            customer_id = data['customer_id']
            selected_customer = get_selected_customer(context.user_data)
            if selected_customer and selected_customer['customer_id'] == customer_id:
                new_balance = (await db.get_customer_by_id(customer_id, admin_id))['balance']
                update_context(context.user_data, balance=new_balance)
        case "delete_customer":
            pass
        case "rename_customer":
            customer_id = data['customer_id']
            new_name = data['new_name']
            selected_customer = get_selected_customer(context.user_data)
            if selected_customer and selected_customer['customer_id'] == customer_id:
                update_context(context.user_data, fullname=new_name)
        case "change_phone":
            pass
async def handle_service_result(update, res: Dict, fail_return = None, fail_markup = None, fail_msg_intro = ''):
    if not res['ok']:
        feedback = "\n".join(res['msg']) if len(res['msg']) > 0 else ""
        await update.effective_message.reply_text(
            text= fail_msg_intro + "\n" + feedback,
            reply_markup=fail_markup, parse_mode='HTML'
        )
        return fail_return
    if len(res['msg']) > 0:
        feedback = "\n".join(res['msg'])
        await update.effective_message.reply_text(text=feedback, parse_mode='HTML')
    
