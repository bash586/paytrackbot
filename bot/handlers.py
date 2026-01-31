from dataclasses import dataclass
from typing import Dict, List, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler
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

async def search(query, limit, db_manager: DatabaseManager, admin_id: int, mode: Optional[str] = None):

    customers = await db_manager.search_customers(query, limit, admin_id)
    if not customers:
        return
    # Show each search result as a user-selectable option.
    
    mode = '' if not mode else ':' + mode
    return [
        [
            InlineKeyboardButton(
                customer['fullname'].upper(),
                callback_data=f"customer_select:{customer['id']}{mode}",
            )
        ]
        for customer in customers
    ]

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    db_manager: DatabaseManager = context.bot_data['db_manager']
    admin_id = update.effective_user.id

    keyboard = await search(query, limit, db_manager, admin_id)

    if not keyboard:
        await update.effective_message.reply_text("No customers found")

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
    query_parts = query.data.split(":")

    customer_id = int(query_parts[1])
    admin_id = update.effective_user.id
    db_manager: DatabaseManager = context.bot_data['db_manager']

    selected_customer = await select_customer(customer_id, admin_id, db_manager, context.user_data)
    if not selected_customer:
        logger.warning("Selected Customer can not be Found")
        await query.edit_message_text("Customer not found or was deleted")
        return

    if len(query_parts) > 2:
        mode = query_parts[2]
        if mode == 'transactions_report':
            page = await db_manager.fetch_transactions_page(customer_id, admin_id, 5)
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
                buttons.append([
                    InlineKeyboardButton("→", callback_data=f"report:customer_transaction_history:{page['next_cursor']}:2:forwards")
                ])

            buttons.append([InlineKeyboardButton("←", callback_data=f"report:main:0:0:backwards")])
            await query.edit_message_text(
                text=message,
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode="HTML"
            )
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

# ---------------------------------------------------------------------------
# Search Conversation Handlers
# ---------------------------------------------------------------------------

async def ask_search_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    query format:
            wait_search_query:<mode>
    * all modes : {'transactions_report',}
    """
    query = update.callback_query
    await query.answer()

    parts_str = query.data
    parts = parts_str.split(":")
    if len(parts) < 2:
        await query.edit_message_text("Invalid request")
        return ConversationHandler.END
    mode = parts[1]

    msg_id = update.effective_message.id
    report_navigator = context.user_data.get('report_navigator')
    if ( report_navigator is None
    or ( report_navigator['mode'] != ReportView.CUSTOMER_TRANSACTION_HISTORY or report_navigator['msg_id'] != msg_id )):
        report_navigator = init_report_ctx(context.user_data, ReportView.CUSTOMER_TRANSACTION_HISTORY, msg_id, 1)

    reply_keyboard = [
        [InlineKeyboardButton("Home", callback_data="report:main:0:0:backwards")]
    ]

    await query.edit_message_text(
        "To proceed with your request, please enter a customer name:",
        reply_markup=InlineKeyboardMarkup(reply_keyboard),
    )
    ASK_QUERY = 0
    return ASK_QUERY

async def recieve_search_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_query = update.message.text
    db_manager = context.bot_data['db_manager']
    admin_id = update.effective_user.id
    keyboard = await search(search_query, 5, db_manager, admin_id, 'transactions_report')
    msg_id = context.user_data.get("report_navigator",dict()).get('msg_id')
    await update.effective_message.delete()
    if not keyboard:
        reply_keyboard = [[
            InlineKeyboardButton(
                text="Home",
                callback_data="report:main:0:0:forwards",
            )
        ]]

        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=msg_id,
            text=(
                f"No customers found with name: <b>{search_query}</b>.\n "
                "Please enter a customer name to search for:\n\n"
            ),
            reply_markup=InlineKeyboardMarkup(reply_keyboard),
            parse_mode='HTML'
        )
        ASK_QUERY = 0
        return ASK_QUERY
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=msg_id,
        text=(
            "You can select one customer to view their history of transactions:\n\n"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

    return ConversationHandler.END


async def search_transactions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Callback handler for when user selects a customer from search results to view transactions.
    Fetches the first page of transactions for the selected customer.
    """
    query = update.callback_query
    await query.answer()

    # Extract customer ID from callback data
    customer_id = int(query.data.split(":", maxsplit=1)[1])
    admin_id = update.effective_user.id
    db_manager: DatabaseManager = context.bot_data['db_manager']

    # Select the customer and store in context
    selected_customer = await select_customer(customer_id, admin_id, db_manager, context.user_data)

    if not selected_customer:
        logger.warning("Selected Customer can not be found")
        await query.edit_message_text("Customer not found or was deleted")
        return
    
    # Fetch the first page of transactions for the selected customer
    try:
        transactions_page = await db_manager.fetch_transactions_page(
            customer_id=customer_id,
            admin_id=admin_id,
            limit=5,
            cursor=None  # Start from the beginning
        )

        # Format transactions for display
        items = transactions_page.get('items', [])
        if not items:
            message = f"<b>「✦{selected_customer['fullname'].upper()}✦</b>\n\nNo transactions found."
        else:
            transactions_text = []
            for i, transaction in enumerate(items):
                transactions_text.append(format_transaction(transaction, i == len(items) - 1))
            transactions_formatted = "".join(transactions_text)
            message = f"<b>「✦{selected_customer['fullname'].upper()}✦</b>\n\n{transactions_formatted}"
        
        await query.edit_message_text(
            text=message,
            parse_mode="HTML"
        )
        
    except Exception as exc:
        logger.error(f"Error fetching transactions page: {exc}")
        await query.edit_message_text("Error fetching transactions. Please try again later.")

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

    _, mode, cursor_str, page_num_str, direction = parts
    msg_id = update.effective_message.message_id

    report_navigator = context.user_data.get('report_navigator')

    try:
        page_index = int(page_num_str)
    except ValueError as exc:
        await query.edit_message_text("Invalid request parameters")
        logger.warning(f"Invalid request parameters: " + str(exc))
        return

    if ( report_navigator is None
    or ( report_navigator['mode'] != mode or report_navigator['msg_id'] != msg_id )):
        # prev_report_msg_id = report_navigator.get('msg_id', None) if report_navigator else None
        # # delete old report navigator if any...
        # if prev_report_msg_id is not None and prev_report_msg_id != msg_id:
        #     await context.bot.delete_message(
        #         chat_id=update.effective_chat.id,
        #         message_id=prev_report_msg_id,
        #     )
        report_navigator = init_report_ctx(context.user_data, mode, msg_id, page_index)
    report_navigator['page_index'] = page_index
    db_manager: DatabaseManager = context.bot_data['db_manager']
    admin_id = update.effective_user.id

    if mode in (
        ReportView.DUE_CUSTOMERS,
        ReportView.OVERPAID_CUSTOMERS,
    ):

        # required params: page_num_str, cursor_str, query, db_manager, report_navigator
        cursor = None
        try:
            if cursor_str != '0' and cursor_str != 'None':
                cursor_list = cursor_str.split(',')
                cursor = (float(cursor_list[0]), int(cursor_list[1]),)

        except ValueError as exc:
            await query.edit_message_text("Invalid request parameters")
            logger.warning(f"Invalid request parameters: " + str(exc))
            return

        page = await fetch_next_page(report_navigator, db_manager, direction, cursor, mode, admin_id)
        if page is None:
            keyboard = generate_report_menu_keyboard()
            await query.edit_message_text(
                text="Select a report to view:", #bookmark: change text
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
                "\n"+"\t"*20+f"➺ Balance: {it['balance']:.2f}"
                "\n────୨ৎ────\n"
            )
        text = "\n".join(lines)
        buttons = []
        if page['has_more'] and page['next_cursor']:
            buttons.append([
                InlineKeyboardButton("→", callback_data=f"report:{mode}:{page['next_cursor']}:{page_index+1}:forwards")
            ])

        if page_index > 1:
            prev_cursor = page.get('prev_cursor','0')
            buttons.append([InlineKeyboardButton("←", callback_data=f"report:{mode}:{prev_cursor}:{page_index-1}:backwards")])
        else:
            buttons.append([InlineKeyboardButton("←", callback_data="report:main:0:0:backwards")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return
    elif mode == ReportView.OVERALL_SUMMARY:
        totals_dict = await db_manager.fetch_overall_report(admin_id)
        report_str = (
            f"<b>✱ Total Payment Needed:\n"
            "\n"+"\t"*20+f"➺ {totals_dict['due_total']:.2f}"
            "\n\n────୨ৎ────\n\n"
            f"✱ Total Credit Available:\n"
            "\n"+"\t"*20+f"➺ {totals_dict['overpaid_total']:.2f}"
            "\n\n────୨ৎ────\n\n"
            f"✱ Overall Credit:\n"
            "\n"+"\t"*20+f"➺ {totals_dict['overall_total']:.2f}\n</b>"
        )
        buttons = [[InlineKeyboardButton("←", callback_data="report:main:0:0:backwards")]]
        await query.edit_message_text(report_str, reply_markup=InlineKeyboardMarkup(buttons),parse_mode='HTML')
        return
    elif mode == ReportView.CUSTOMER_TRANSACTION_HISTORY:
        cursor = None
        try:
            if cursor_str != 'None' and cursor_str != '0':
                cursor = int(cursor_str)
        except ValueError as exc:
            await query.edit_message_text("Invalid request parameters")
            logger.warning(f"Invalid request parameters: " + str(exc))
            return

        selected_customer = get_selected_customer(context.user_data)
        if not selected_customer:
            await query.edit_message_text("Unexpected Error: no customer is selected")
            return
        customer_id = selected_customer['customer_id']            

        page = await fetch_next_page(report_navigator, db_manager, direction, cursor, ReportView.CUSTOMER_TRANSACTION_HISTORY, admin_id, customer_id)
        if not page:
            await query.edit_message_text("Page is not Fetched Correctly. contact the idiot we call 'developer'")
            logger.warning(f"Transactions Report Page is not Fetched Correctly...")
            return

        items: Optional[List[Customer]] = page['items']
        if not items:
            await query.edit_message_text("No Transactions Found.")
            return

        transactions_text = []
        for i, transaction in enumerate(items):
            transactions_text.append(format_transaction(transaction, i == len(items) - 1, include_details=True))
        transactions_formatted = "".join(transactions_text)

        message = f"<b>{selected_customer['fullname'].upper()}</b> - Transactions:\n\n{transactions_formatted}"


        buttons = []

        if page['has_more'] and page['next_cursor']:
            buttons.append([
                InlineKeyboardButton("→", callback_data=f"report:{mode}:{page['next_cursor']}:{page_index+1}:forwards")
            ])

        if page_index > 1:
            prev_cursor = page.get('prev_cursor','0')
            buttons.append([InlineKeyboardButton("←", callback_data=f"report:{mode}:{prev_cursor}:{page_index-1}:backwards")])
        else:
            buttons.append([InlineKeyboardButton("←", callback_data=f"report:main:0:0:backwards")])
        await query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )
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
                text="Transactions History For ...",
                callback_data=f"wait_search_query:transactions_report",
            )
        ],
    ]

def init_report_ctx(user_data: Dict, mode :str, msg_id :int, page_index: int):
    report_navigator = {
        'backwards':[],
        'forwards': [],
        'currently_viewed': None,
        'mode': mode,
        'msg_id':msg_id,
        'page_index': page_index,
    }
    user_data['report_navigator'] = report_navigator
    return report_navigator

async def fetch_next_page(report_navigator: Dict, db_manager: DatabaseManager, direction: str, cursor, mode: str, admin_id: int, customer_id: int=None):
    last_viewed_pg = report_navigator.get('currently_viewed')
    if direction == 'forwards':

        # push current page to backwards stack
        if last_viewed_pg is not None:
            report_navigator['backwards'].append(last_viewed_pg)

        # reuse cached forwards page if exists
        forwards_stack = report_navigator.get('forwards')
        if forwards_stack:
            next_pg = forwards_stack.pop()
            report_navigator['currently_viewed'] = next_pg
            return next_pg

    elif direction == 'backwards':

        # push current page to forwards stack
        if last_viewed_pg is not None:
            report_navigator['forwards'].append(last_viewed_pg)

        if report_navigator['page_index'] < 1:
            return None  # go back to main menu

        backwards_stack = report_navigator.get('backwards')
        if backwards_stack:
            next_pg = backwards_stack.pop()
            report_navigator['currently_viewed'] = next_pg
            return next_pg

    else:
        raise ValueError(f"Invalid navigation direction: {direction}")

    # fetch new page from DB
    page = None
    if mode == ReportView.DUE_CUSTOMERS or mode == ReportView.OVERPAID_CUSTOMERS:
        page = await db_manager.fetch_balances_page(mode, admin_id, 5, cursor)
    elif mode == ReportView.CUSTOMER_TRANSACTION_HISTORY:
        if not customer_id:
            logger.warning("Unexpected Error: no Customer is selected for transactions report!")
        page = await db_manager.fetch_transactions_page(customer_id, admin_id, 5, cursor)

    # set previous cursor for back button
    if last_viewed_pg is not None and direction == 'forwards':
        page['prev_cursor'] = last_viewed_pg.get('cur_cursor')

    report_navigator['currently_viewed'] = page
    return page
