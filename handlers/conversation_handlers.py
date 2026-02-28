# Conversation state machine handlers
from typing import Dict
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler
from utils.utils import (
    get_args,
    get_selected_customer,
    clear_conversation_ctx,
)
from services.database_service import DatabaseManager
from utils.types import ReportView
from config import (
    WELCOME_MSG,
    RECEIVE_ARGS,
    RECEIVE_QUERY,
    ASK_QUERY,
    PROMPT_CUSTOMER_SEARCH,
    CANCEL_KEYBOARD,
    ALLOWED_COMMANDS,
    ALLOWED_SEARCH_MODES,
    FEEDBACK_AVAILABLE_COMMANDS,
)
from handlers.customer_handlers import add_transaction
from handlers.report_handlers import init_report_ctx, get_search_results
import logging
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if update.effective_message:
        await update.effective_message.reply_html(WELCOME_MSG)

async def ask_command_args(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process command invocation and route to appropriate handler."""

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
    if mode == "addtransaction":
        context.user_data["active_command"] = "addtransaction"
        selected_customer = get_selected_customer(context.user_data)
        if args:
            if selected_customer:
                context.user_data["active_command_args"] = args
                return await receive_command_args(update, context)
            context.user_data["active_command_args"] = args
        if not selected_customer:
            return await ask_search_query(update, context)
        from config import PROMPT_TRANSACTION_DETAILS
        await update.effective_message.reply_text(PROMPT_TRANSACTION_DETAILS, reply_markup=InlineKeyboardMarkup(CANCEL_KEYBOARD), parse_mode="HTML")
        return RECEIVE_ARGS
    
    if mode == "addcustomer":
        context.user_data["active_command"] = "addcustomer"
        if args:
            context.user_data["active_command_args"] = args
            return await receive_command_args(update, context)
        # Cleanup and end conversation
        from config import PROMPT_NEW_CUSTOMER_INFO
        await update.effective_message.reply_text(PROMPT_NEW_CUSTOMER_INFO, reply_markup=InlineKeyboardMarkup(CANCEL_KEYBOARD), parse_mode="HTML")
        return RECEIVE_ARGS

async def receive_command_args(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process command arguments after user input."""
    active_command = context.user_data.get("active_command")
    if not active_command or active_command not in ALLOWED_COMMANDS:
        logger.error(f"Invalid active_command: {active_command}")
        await update.effective_message.reply_text("Invalid command state")
        # Cleanup and end conversation on error
        clear_conversation_ctx(context.user_data)
        return ConversationHandler.END
    args = get_args(context.user_data.get('active_command_args', ''))
    if not args:
        args = get_args(update.message.text)
    if not args:
        logger.warning(f"No arguments provided for command: {active_command}")
        await update.effective_message.reply_text(text="No arguments provided. Please enter transaction details.", reply_markup=InlineKeyboardMarkup(CANCEL_KEYBOARD), parse_mode='HTML')
        return RECEIVE_ARGS
    if active_command == "addtransaction":
        res: Dict = await add_transaction(args, update, context)
        if res['ok'] == False:
            if len(res['log_msg']) > 0:
                logger.error("\n".join(res['log_msg']))
            feedback = "\n".join(res['msg']) if len(res['msg']) > 0 else ""
            await update.effective_message.reply_text(text="Failed to add new Transaction...\n" + feedback, reply_markup=InlineKeyboardMarkup(CANCEL_KEYBOARD), parse_mode='HTML')
            return RECEIVE_ARGS
        feedback = "\n".join(res['msg']) if len(res['msg']) > 0 else ""
        await update.effective_message.reply_text(text=feedback, parse_mode='HTML')
    
    if active_command == "addcustomer":
        from services.customer_service import add_customer
        from services.database_service import DatabaseManager
        if len(args) < 2:
            from config import INVALID_USAGE
            err_msg = INVALID_USAGE['addcustomer']
            await update.effective_message.reply_html(err_msg)
            return RECEIVE_ARGS
        from utils.utils import normalize_fullname, normalize_phone
        fullname = normalize_fullname(args[0])
        phone = normalize_phone(args[1])
        if not fullname or not phone:
            from config import INVALID_USAGE
            err_msg = INVALID_USAGE['addcustomer']
            await update.effective_message.reply_html(err_msg)
            return RECEIVE_ARGS
        db_manager: DatabaseManager = context.bot_data['db_manager']
        admin_id = update.effective_user.id
        res: Dict = await add_customer(fullname, phone, admin_id, db_manager, context.user_data, True)
        if not res['ok']:
            if len(res['log_msg']) > 0:
                logger.error("\n".join(res['log_msg']))
            feedback = "\n".join(res['msg']) if len(res['msg']) > 0 else ""
            await update.effective_message.reply_text(text="Failed to add new Customer...\n" + feedback, reply_markup=InlineKeyboardMarkup(CANCEL_KEYBOARD), parse_mode='HTML')
            return RECEIVE_ARGS
        feedback_msg = "\n".join(res['msg']) if len(res['msg']) > 0 else ""
        await update.effective_message.reply_html(text=f"{feedback_msg}\n{FEEDBACK_AVAILABLE_COMMANDS}")

    # cleanup and end conversation
    clear_conversation_ctx(context.user_data)
    logger.info(f"User {update.effective_user.id} completed conversation successfully")
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
    db_manager = context.bot_data['db_manager']
    admin_id = update.effective_user.id
    args = get_args(update.message.text)
    search_query = args[0]
    limit = args[1] if len(args) > 1 else 5
    search_mode = context.user_data["search_mode"]
    keyboard = await get_search_results(search_query, limit, db_manager, admin_id, search_mode)
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
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg_id, text=("To Proceed, Select one Customer:\n\n"), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
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
    - Commands executed while in conversation
    """
    # Clean up all user context data
    clear_conversation_ctx(context.user_data)
    
    # Identify what triggered the end
    if update.callback_query:
        # User clicked the Cancel button
        query = update.callback_query
        await query.answer("Conversation cancelled")
        await query.delete_message()
        logger.info(f"User {update.effective_user.id} cancelled conversation via cancel button")
    elif update.effective_message:
        # User sent a message (likely a new command)
        logger.info(f"User {update.effective_user.id} exited conversation via new command: {update.effective_message.text}")
    
    return ConversationHandler.END

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /undo command to revert the last action."""
    db_manager: DatabaseManager = context.bot_data['db_manager']
    admin_id = update.effective_user.id
    feedback_msg = await db_manager.undo_last_action_for_admin(admin_id, context.user_data)
    await update.effective_message.reply_html(feedback_msg)
