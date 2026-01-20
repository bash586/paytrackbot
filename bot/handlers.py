from dataclasses import dataclass
from typing import Dict, List, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from bot.helpers import (
    format_date,
    format_summary_html,
    format_transaction,
    get_selected_customer,
    is_valid_name,
    normalize_fullname,
    is_valid_phone,
    get_args,
    normalize_name,
    normalize_phone,
    set_selected_customer,
    update_context,
)
import json
from datetime import datetime
from bot.customer_service import (
    select_customer,
    add_customer,
    delete_customer,
    rename_customer,
    change_phone,
)
from bot.database_manager import DatabaseManager
from bot.types import ActionType, Customer, ReportView, Transaction
from config import (
    INVALID_USAGE,
    NO_SELECTED_CUSTOMER_WARNING,
    WELCOME_MSG,
)
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# General Command handlers
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
    if update.effective_message:
        await update.effective_message.reply_html(WELCOME_MSG)

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
        [
            InlineKeyboardButton(
                customer['fullname'].upper(),
                callback_data=f"customer_select:{customer['id']}",
            )
        ]
        for customer in customers
    ]

    await update.effective_message.reply_text(
        text='Choose One Customer:',
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

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

    for i in range(len(recent)):
        item = recent[i]
        recent_actions.append(format_transaction(item, i == len(recent)-1))
    recent_actions_formatted = (
        "".join(recent_actions) if len(recent_actions) > 0 else "No transactions found."
    )
    logger.info(f"payments {summary['payments']:.1f}")

    message = format_summary_html(summary, recent_actions_formatted)
    await update.effective_message.reply_html(text=message)


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

async def add_transaction_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await db_manager.add_transaction(amount, type_, description, customer_id, admin_id)
    except Exception as exc:
        await update.effective_message.reply_text("Something went wrong. Please try again later.")
        return
    new_balance = (await db_manager.get_customer_by_id(customer_id, admin_id))['balance']
    # update context in a single place
    update_context(context.user_data, balance=new_balance)


    feedback_msg = '\n'.join([
            f"「 ✦<b>{fullname.upper()}</b>✦ 」",
            "  ─•────",
            f"Successfully added <b>{type_.upper()}</b> of <b>{amount:.2f}</b>",
            f"<b>Description: </b> {description}" if len(args)>2 else '',
            f"\n<b>Account Balance: {new_balance:.2f}</b>",
    ])

    await update.effective_message.reply_html(feedback_msg)

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

async def rename_customer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # get selected customer
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


async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_manager: DatabaseManager = context.bot_data['db_manager']
    admin_id = update.effective_user.id
    feedback_msg = await db_manager.undo_last_action_for_admin(admin_id, context.user_data)
    await update.effective_message.reply_html(feedback_msg)


async def report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pager callbacks for transactions and balances

    Callback formats:
      main:0:0:forwards
      <view-mode>:<cursor>:<page-num>:<direction>
    """
    query = update.callback_query
    await query.answer()

    parts_str = query.data
    parts = parts_str.split(":")
    if len(parts) != 5:
        await query.edit_message_text("Invalid Report request")
        return

    context.user_data.setdefault('report_pages', [])
    context.user_data.setdefault('cur', 0)

    _, mode, cursor_str, page_num_str, direction = parts
    msg_id = update.effective_message.message_id

    report_navigator = context.user_data.get('report_navigator')
    logger.debug(report_navigator)
    if ( report_navigator is None
    or ( report_navigator['mode'] != mode or report_navigator['msg_id'] != msg_id )):
        report_navigator = init_report_ctx(context.user_data, mode, msg_id)

    db_manager: DatabaseManager = context.bot_data['db_manager']
    admin_id = update.effective_user.id

    if mode in (
        ReportView.DUE_CUSTOMERS,
        ReportView.OVERPAID_CUSTOMERS,
    ):
        # required params: page_num_str, cursor_str, query, db_manager, report_navigator
        cursor, page_index = None, None
        try:
            page_index = int(page_num_str)
            if cursor_str == '0':
                cursor_str = None
            else:
                cursor_list = cursor_str.split(',')
                cursor = (float(cursor_list[0]), int(cursor_list[1]),)

        except ValueError as exc:
            await query.edit_message_text("Invalid request parameters")
            logger.warning(f"Invalid request parameters: " + str(exc))
            return

        page = await fetch_next_page(report_navigator, admin_id, db_manager, direction, cursor, mode)
        if page is None:
            keyboard = generate_report_menu_keyboard()
            await query.edit_message_text(
                text="Select a report to view:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        items: Optional[List[Customer]] = page['items']
        if not items:
            await query.edit_message_text("No Balances Found.")
            return

        lines = []
        for i in range(len(items)):
            it = items[i]
            lines.append(
                f"✱ {it['fullname'].upper()}"
                "\n"+"\t"*15+f"➺ Balance: {it['balance']:.2f}"
                "\n────୨ৎ────\n"
            )
        text = "\n".join(lines)
        buttons = []
        if page['has_more'] and page['next_cursor']:
            buttons.append([
                InlineKeyboardButton("→", callback_data=f"report:{mode}:{page['next_cursor']}:{page_index+1}:forwards")
            ])

        if page_index > 1:
            buttons.append([InlineKeyboardButton("←", callback_data=f"report:{mode}:0:{page_index-1}:backwards")])
        else:
            buttons.append([InlineKeyboardButton("←", callback_data=f"report:main:0:0:backwards")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return
    elif mode == ReportView.OVERALL_SUMMARY:
        return
    elif mode == ReportView.CUSTOMER_TRANSACTION_HISTORY:

        return
    elif mode == "main":
        keyboard = generate_report_menu_keyboard()
        await query.edit_message_text(
            text="Select a report to view:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    await query.edit_message_text("Invalid View Mode")

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = generate_report_menu_keyboard()

    await update.effective_message.reply_text(
        text="Select a report to view:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

def generate_report_menu_keyboard():
    return [
        [
            InlineKeyboardButton(
                text="Due — Payment Needed",
                callback_data=f"report:{ReportView.DUE_CUSTOMERS.value}:0:1:forwards",
            )
        ],
        [
            InlineKeyboardButton(
                text="Overpaid — Credit Available",
                callback_data=f"report:{ReportView.OVERPAID_CUSTOMERS.value}:0:1:forwards",
            )
        ],
        [
            InlineKeyboardButton(
                text="Overall Summary",
                callback_data=f"report:{ReportView.OVERALL_SUMMARY.value}:0:1:forwards",
            )
        ],
        [
            InlineKeyboardButton(
                text="Transactions History",
                callback_data=f"report:{ReportView.CUSTOMER_TRANSACTION_HISTORY.value}:0:1:forwards",
            )
        ],
    ]

def init_report_ctx(user_data: Dict, mode :str, msg_id :int):

    user_data.setdefault('report_navigator',dict())
    report_navigator = {
        'backwards':[],
        'forwards': [],
        'currently_viewed': None,
        'mode': mode,
        'msg_id':msg_id,
        'page_index': 1,
    }
    user_data['report_navigator'] = report_navigator
    return report_navigator

async def fetch_next_page(report_navigator, admin_id, db_manager, direction, cursor, mode):

    if direction == 'forwards':
            report_navigator['page_index'] += 1
            last_viewed_pg = report_navigator['currently_viewed']
            if last_viewed_pg is not None:
                report_navigator['backwards'].append(last_viewed_pg)
            forwards_stack = report_navigator.get('forwards', [])
            if len(forwards_stack) > 0:
                next_pg = forwards_stack.pop()
                report_navigator['currently_viewed'] = next_pg
                return next_pg

    elif direction == 'backwards':
        report_navigator['page_index'] -= 1

        if report_navigator['page_index'] == 1:
            return # return home

        backwards_stack = report_navigator.get('backwards', [])
        if len(backwards_stack) > 0:
            next_pg = backwards_stack.pop()
            report_navigator['currently_viewed'] = next_pg
            return next_pg
    else:
        raise ValueError('invalid navigation direction: ' + direction)

    page = await db_manager.fetch_balances_page(mode,admin_id, 5, cursor)
    report_navigator['currently_viewed'] = page
    return page