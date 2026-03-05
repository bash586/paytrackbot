# PayTrackBot

## Problem This Bot Addresses

PayTrackBot is a Telegram bot built for shop owners who rely on credit-based sales. It replaces messy paper records with a fast, chat-based system to track who owes what — right from your phone. It lets you:

- Add new customers and manage their balances.
- Record sale/payment transactions for customers.
- Search for customers by name or phone number.
- View a customer overview.
- Delete, rename, or update a customer's phone number.
- Undo the last recorded action (adding a customer/transaction, deleting, renaming, or changing a phone number).
- View various kinds of reports: due payments, overdue payments, etc.

## How to Install and Run on Your Local Machine

1. **Install `uv`** (Python package and project manager):
   ```bash
   # Linux / macOS
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # Windows (PowerShell)
   irm https://astral.sh/uv/install.ps1 | iex
   ```
   After installation, restart your terminal so the `uv` command is available.

2. **Create a Telegram bot via BotFather:**
   - Open Telegram and search for **@BotFather**.
   - Send `/newbot` and follow the prompts (choose a name and username for your bot).
   - Copy the **API token** BotFather provides — you'll need it in step 6.

3. **Add commands to the bot menu:**
   - In the same **@BotFather** chat, send `/setcommands`.
   - Select your bot when prompted.
   - Paste the following command list:
     ```
     addtransaction - Record a credit transaction
     addcustomer - Add a new customer
     search - Search for a customer
     info - View customer overview
     undo - Undo the last action
     report - View a balance report
     rename - Rename a customer
     changephone - Change customer phone number
     delete - Delete a customer
     ```
   - BotFather will confirm the commands have been set.

4. **Clone the repository:**
   ```bash
   git clone https://github.com/bash586/paytrackbot.git
   cd paytrackbot
   ```

5. **Set up the Python environment** (requires Python 3.12+):
   ```bash
   uv venv
   source .venv/bin/activate   # Linux/macOS
   # .venv\Scripts\activate    # Windows
   uv sync
   ```

6. **Configure the environment variables:**
   Create a `.env` file in the root directory and paste your bot token:
   ```env
   BOT_TOKEN=your_telegram_bot_token_here
   ```

7. **Run the bot:**
   ```bash
   uv run main.py
   ```

> The database (SQLite) is initialized automatically on first startup.

## Technology Stack

| Layer               | Technology                         |
| ------------------- | ---------------------------------- |
| Language            | Python 3.12+                       |
| Bot Framework       | `python-telegram-bot` v21.6        |
| Database            | SQLite (async via `aiosqlite`)     |
| Environment Config  | `python-dotenv`                    |
| Testing             | `pytest`, `pytest-asyncio`         |
| Dependency Manager  | `uv`                               |
