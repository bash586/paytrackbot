# PayTrackBot

### We’ll build a Telegram bot for managing deferred (credit) payments — e.g., allowing the store owner to:

1. Register customers.

2. Record new purchases on credit.

3. Track outstanding balances and payment history.

4. Mark payments as settled.

## Actions/Commands

| Action             | Command Example                 | Description                                     |
| ------------------ | ------------------------------- | ----------------------------------------------- |
| Add a customer     | `/addcustomer John\|0590000000`  | Creates a new customer record                   |
| Record transaction | `/addtransaction 50\|groceries`  | Adds a deferred payment of $50                  |
| List all customers | `/search`                       | Lists customers and their balances              |
| search customers   | `/search name`  `/search phone` | Lists customers for user to select one customer |
| View customer info | `/summary`                      | display main info about selected customer       |
| view last actions  | `/history`                      | shows last actions made by admin                |
| undo action        | `/undo`                         | enables admin to undo selected action           |

### Check List:
* add search_transaction command displaying all details of related transactions
* show user a loader until transaction is commited
* remove customer account. or auto-delete customers with zero balance.
* enable user to add parameters to commands in conversation mode
* enable users to change customer's name.
* enable user to add a link between multiple customer accounts.
* enable users to merge multiple records of customers into one record.
* add help command to guide users.
* if there is only one search result. select automatically
* add a password check for add_payment command and changing customer name.
* show your creative touch with tags
* enable users to add hidden nicknames, and store it in customers(name) field with a special delimeter
* output excel summary **[unfortunately, may be a dream out of my reach]**

## Tech Stack

Language: Python

Library: python-telegram-bot

Database: _______

Deployed by: _____ (consider "Render")

Optional: dotenv for managing bot tokens


user_data = {

    context_state = {
        "selected_customer": {
            "id": customer['id'],
            "fullname": customer['fullname'],
            "balance": customer['balance'],
        }
        "current_action": None #bookmark: to be removed
    }
}
action_data = {
    action: None,
    action_date: None,
    admin_id: None,
    customer_id: None,
    action_info: {
        <!-- rename -->
        oldname: None,
        <!-- delete customer -->
        fullname, created_at, balance, phone
        <!-- transaction -->
        amount, type, created_at, id, description
    }
}