# Configuration and constants for paytrackbot
from os import path
from telegram import InlineKeyboardButton

DEFAULT_PHONE_PATTERN = r"^\+?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}$"
DEFAULT_NAME_PATTERN = r"^[A-Za-z\-\']{2,20}(\s[A-Za-z]{1,20}){0,3}\s[A-Za-z]{2,20}$"
DATABASE_PATH = path.join("data","app_database.db")
NO_SELECTED_CUSTOMER_WARNING = """<b>Error: you must select a customer first...</b>

<code>/search query</code>*

 query* : <b>name</b>/<b>phone</b>
 Note: <code>/search</code> will display all your customers
"""
INVALID_USAGE = {
    "addtransaction": (
        "<b>Please use this format...</b>\n\n"
        "<code>/addtransaction\n"
        "[±amount]  ( '-' :SALE | '+':PAYMENT )\n"
        "[info]</code>"
    ),
    "addcustomer": '\n'.join([
        f"<b>Incorrect Command Usage...</b>",
        "Usage: <code>/addcustomer fullname*|phone*</code>"
    ]),
    "rename":'\n'.join([
        "<b>Incorrect Command Usage...</b>",
        "Usage: <code>/rename newname*</code>",
    ]),
    "changephone": '\n'.join([
        "<b>Incorrect Command Usage...</b>",
        "Usage: <code>/changephone newphone*</code>",
    ])
    
}

# ---------------------------------------------------------------------------
# Conversation State Management Messages
# ---------------------------------------------------------------------------

PROMPT_TRANSACTION_DETAILS = (
    "To proceed, please <b>enter transaction details ...</b>\n\n"
    "Please use this format:\n"
    "   <b>[Amount]</b>\n"
    "   <b>[Description]</b>\n"
)

PROMPT_NEW_CUSTOMER_INFO = (
    "To proceed, please <b>enter transaction details ...</b>\n\n"
    "Please use this format:\n"
    "   <b>[Fullname]</b>\n"
    "   <b>[Phone]</b>\n"
)

PROMPT_CUSTOMER_SEARCH = (
    "To proceed, please <b>enter a customer Name/Phone ...</b>\n\n"
    "Please use this format:\n"
    "   <b>[SearchQuery]</b>\n"
    "   <b>[Limit]</b>                   (default 5)\n"
)

PROMPT_CUSTOMER_SEARCH_INLINE = "To proceed, please <b>enter a customer Name/Phone...</b>"

PROMPT_SELECT_CUSTOMER = "To Proceed, Select one Customer:\n\n"

PROMPT_ENTER_TRANSACTION = (
    "To proceed, please <b>enter transaction details ...</b>\n\n"
    "Please use this format:\n"
    "   <b>[Amount]</b>\n"
    "   <b>[Description]</b>\n"
)

SUCCESS_TRANSACTION_ADDED = (
    "「 ✦<b>{}</b>✦ 」\n"
    "  ─•────\n"
    "Successfully added <b>{}</b> of <b>{:.2f}</b>\n"
    "{}"
    "\n<b>Account Balance: {:.2f}</b>"
)

# Feedback messages
FEEDBACK_AVAILABLE_COMMANDS = '\n'.join([
    "<b>Now, you can:</b>",
    " ● <b>add transaction</b>",
    "   <code>/addtransaction amount|type|info</code>",
    " ● <b>view customer's info</b>",
    "   <code>/summary</code>",
    " ● <b>update customer's name</b>",
    "   <code>/rename newName</code>",
    " ● <b>update customer's phone</b>",
    "   <code>/changephone newPhone</code>",
    " ● <b>delete customer</b>",
    "   <code>/delete</code>",
])

WELCOME_MSG = """
<b>Welcome to the Pay Track Bot

I am here to help you manage customers, balances, and cash flow.  
Use the commands below as your quick reference.</b>

<b>Customer Management</b>
<code>/addcustomer Full Name | Phone</code>
Create a customer.

<code>/search query | limit</code>
Search by name or phone.

<code>/summary</code>
Show details of the selected customer.

<code>/delete</code>
Remove the selected customer.

<code>/rename New Full Name</code>
Rename the selected customer.

<code>/changephone NewPhone</code>
Update the customer's phone.

<b>Transactions</b>
<code>/addtransaction amount | type | description</code>
Record a transaction.

<code>/transactions limit</code>
View recent transactions.
---

<b>Other Useful Commands</b>
<code>/undo</code> — Undo your last action.
<code>/help</code> — show this cheat-sheet
---

<b>Important Notes</b>
A customer must be selected before running customer-related commands.  
Use <code>/search</code> then select a customer.
---

<b>Example</b>
<code>/addcustomer John Doe | +972501234567
/search johnw
/addtransaction 150 | sale | sold 10 items
/rename John M Doe
/changephone +972598765432</code>

"""


# Conversations CONSTANTS
ASK_QUERY = 0
RECEIVE_QUERY = 1
RECEIVE_ARGS = 2
# Allowed commands and modes (immutable for performance)
ALLOWED_COMMANDS = frozenset(['addtransaction', 'addcustomer'])
ALLOWED_SEARCH_MODES = frozenset(['default', 'transactions_report'])

# Cached keyboard buttons (reuse instead of recreating)
CANCEL_BUTTON = InlineKeyboardButton("Cancel", callback_data="end_conversation")
CANCEL_KEYBOARD = [[CANCEL_BUTTON]]