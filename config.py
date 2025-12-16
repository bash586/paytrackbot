from os import path

DEFAULT_PHONE_PATTERN = r"^\+?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}$"
DEFAULT_NAME_PATTERN = r"^[A-Za-z\-\']{2,20}(\s[A-Za-z]{1,20}){0,3}\s[A-Za-z]{2,20}$"
DATABASE_PATH = path.join("data","app_database.db")
NO_SELECTED_CUSTOMER_WARNING = """<b>Error: you must select a customer first...</b>

<code>/search query</code>*

 query* : <b>name</b>/<b>phone</b>
 Note: <code>/search</code> will display all your customers
"""
INVALID_USAGE = {
    "addtransaction": '\n'.join([
        "<b>Incorrect Command Usage...</b>",
        "Usage: <code>/addtransaction amount*|type*|info</code>",
        "type*: '<b>sale</b>' or '<b>payment</b>' ",
    ]),
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