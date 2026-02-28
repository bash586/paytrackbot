# Report-related Telegram handlers

from typing import Dict, List, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from utils.utils import parse_pagination_cursor, get_selected_customer
from utils.utils import format_transaction
from services.database_service import DatabaseManager
from services.customer_repository import CustomerRepository
from services.report_repository import ReportRepository
from utils.types import Customer, ReportView
import logging

logger = logging.getLogger(__name__)


async def get_search_results(query, limit, db_manager: DatabaseManager, admin_id: int, mode: Optional[str] = None):
    """Search customers and return keyboard with results."""
    customer_repo = CustomerRepository(db_manager.conn)
    customers = await customer_repo.search_customers(query, limit, admin_id)
    if not customers:
        return
    mode = '' if not mode else ':' + mode
    return [[InlineKeyboardButton(customer['fullname'].upper(), callback_data=f"customer_select:{customer['id']}{mode}")] for customer in customers]


def init_report_ctx(user_data: Dict, mode: str, msg_id: int, page_index: int):
    """Initialize report navigator context."""
    report_navigator = {
        'backwards': [],
        'forwards': [],
        'currently_viewed': None,
        'mode': mode,
        'msg_id': msg_id,
        'page_index': page_index,
    }
    user_data['report_navigator'] = report_navigator
    return report_navigator


def generate_report_menu_keyboard():
    """Generate keyboard with report menu options."""
    return [
        [InlineKeyboardButton(text="Due — Payment Needed", callback_data=f"report:{ReportView.DUE_CUSTOMERS.value}:0:1:forwards")],
        [InlineKeyboardButton(text="Overpaid — Credit Available", callback_data=f"report:{ReportView.OVERPAID_CUSTOMERS.value}:0:1:forwards")],
        [InlineKeyboardButton(text="Overall Summary", callback_data=f"report:{ReportView.OVERALL_SUMMARY.value}:0:1:forwards")],
        [InlineKeyboardButton(text="Transactions History For ...", callback_data=f"wait_search_query:transactions_report")],
    ]


async def fetch_next_page(report_navigator: Dict, db_manager: DatabaseManager, direction: str, cursor, mode: str, admin_id: int, customer_id: int = None):
    """Fetch next page based on navigation direction and properly track history."""
    report_repo = ReportRepository(db_manager.conn)
    last_viewed_pg = report_navigator.get('currently_viewed')
    
    # When moving forward, save current page info for backward navigation
    if direction == 'forwards' and last_viewed_pg is not None:
        backward_stack = report_navigator.get('backwards', [])
        backward_stack.append({
            'cursor': last_viewed_pg.get('current_cursor'),
            'next_cursor': last_viewed_pg.get('next_cursor')
        })
        report_navigator['backwards'] = backward_stack
    
    # When moving backward, pop from stack and use that cursor
    if direction == 'backwards':
        backward_stack = report_navigator.get('backwards', [])
        if backward_stack:
            prev_page_info = backward_stack.pop()
            cursor = prev_page_info.get('cursor')
        else:
            cursor = None
    
    page = None
    if mode == ReportView.DUE_CUSTOMERS or mode == ReportView.OVERPAID_CUSTOMERS:
        page = await report_repo.fetch_balances_page(admin_id, mode, 5, cursor)
        page = {
            "items": page[0],
            "next_cursor": page[1],
            "has_more": page[2],
            "current_cursor": cursor,
        }
    elif mode == ReportView.CUSTOMER_TRANSACTION_HISTORY:
        if not customer_id:
            logger.warning("Unexpected Error: no Customer is selected for transactions report!")
        page = await report_repo.fetch_transactions_page(customer_id, admin_id, 5, cursor)
        page['current_cursor'] = cursor  # Track current cursor for history
    
    if page:
        report_navigator['currently_viewed'] = page
    return page


async def report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle report pagination callbacks."""
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
    if (report_navigator is None or (report_navigator['mode'] != mode or report_navigator['msg_id'] != msg_id)):
        report_navigator = init_report_ctx(context.user_data, mode, msg_id, page_index)
    report_navigator['page_index'] = page_index
    db_manager: DatabaseManager = context.bot_data['db_manager']
    admin_id = update.effective_user.id
    if mode in (ReportView.DUE_CUSTOMERS, ReportView.OVERPAID_CUSTOMERS,):
        is_valid, cursor = parse_pagination_cursor(cursor_str, mode)
        if not is_valid:
            await query.edit_message_text("Invalid request parameters")
            return
        page = await fetch_next_page(report_navigator, db_manager, direction, cursor, mode, admin_id)
        if page is None:
            keyboard = generate_report_menu_keyboard()
            await query.edit_message_text(text="Select a report to view:", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        items: Optional[List[Customer]] = page['items']
        if not items:
            await query.edit_message_text("No Balances Found.")
            return
        lines = []
        for i in range(len(items)):
            it = items[i]
            lines.append(f"✱ {it['fullname'].upper()}" "\n"+"\t"*20+f"➺ Balance: {it['balance']:.2f}" "\n────୨ৎ────\n")
        text = "\n".join(lines)
        buttons = []
        if page['has_more'] and page['next_cursor']:
            cursor_str = f"{page['next_cursor'][0]},{page['next_cursor'][1]}"
            buttons.append([InlineKeyboardButton("→", callback_data=f"report:{mode}:{cursor_str}:{page_index+1}:forwards")])
        # Add backward button - use '0' for first page, backwards navigation for others
        if page_index > 1:
            # For backward nav, we use '0' and let fetch_next_page pop from stack
            buttons.append([InlineKeyboardButton("←", callback_data=f"report:{mode}:0:{page_index-1}:backwards")])
        elif page_index == 1:
            # First page - go back to main menu
            buttons.append([InlineKeyboardButton("←", callback_data="report:main:0:0:backwards")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return
    elif mode == ReportView.OVERALL_SUMMARY:
        report_repo = ReportRepository(db_manager.conn)
        totals_dict = await report_repo.fetch_overall_report(admin_id)
        report_str = (f"<b>✱ Total Customers: {totals_dict['total_customers']}\n\t" 
                     f"Due: {totals_dict['due_customers']} | Overpaid: {totals_dict['overpaid_customers']}\n\n"
                     f"✱ Overall Balance: ➺ {totals_dict['total_balance']:.2f}\n"
                     f"✱ Total Transactions: {totals_dict['total_transactions']}\n</b>")
        buttons = [[InlineKeyboardButton("←", callback_data="report:main:0:0:backwards")]]
        await query.edit_message_text(report_str, reply_markup=InlineKeyboardMarkup(buttons),parse_mode='HTML')
        return
    elif mode == ReportView.CUSTOMER_TRANSACTION_HISTORY:
        is_valid, cursor = parse_pagination_cursor(cursor_str, mode)
        if not is_valid:
            await query.edit_message_text("Invalid request parameters")
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
            await query.edit_message_text("No Transactions Found.\n")
            return
        transactions_text = []
        for i, transaction in enumerate(items):
            transactions_text.append(format_transaction(transaction, i == len(items) - 1, include_details=True))
        transactions_formatted = "".join(transactions_text)
        message = f"<b>{selected_customer['fullname'].upper()}</b> - Transactions:\n\n{transactions_formatted}"
        buttons = []
        if page['has_more'] and page['next_cursor']:
            buttons.append([InlineKeyboardButton("→", callback_data=f"report:{mode}:{page['next_cursor']}:{page_index+1}:forwards")])
        if page_index > 1:
            buttons.append([InlineKeyboardButton("←", callback_data=f"report:{mode}:0:{page_index-1}:backwards")])
        else:
            buttons.append([InlineKeyboardButton("←", callback_data=f"report:main:0:0:backwards")])
        await query.edit_message_text(text=message, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
        return
    elif mode == "main":
        keyboard = generate_report_menu_keyboard()
        await query.edit_message_text(text="Select a report to view:", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    await query.edit_message_text("Invalid View Mode")

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /report command."""
    keyboard = generate_report_menu_keyboard()
    await update.effective_message.reply_text(text="Select a report to view:", reply_markup=InlineKeyboardMarkup(keyboard),)


