import asyncio
import logging
import os
from dotenv import load_dotenv
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, CommandHandler, PicklePersistence, PersistenceInput, MessageHandler
)
from bot import handlers
from bot.database_manager import DatabaseManager
from config import DATABASE_PATH

def main():

    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    load_dotenv()
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        raise ValueError("invalid bot token")

    persistence = PicklePersistence(
        filepath="data.pkl",
        update_interval=30,
        store_data=PersistenceInput(chat_data=False),
    )

    db = DatabaseManager(DATABASE_PATH)
    async def on_stop(app):
        await db.close()

    async def on_start(app):
        await db.init_database()
        app.bot_data["db_manager"] = db

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .persistence(persistence)
        .post_init(on_start)
        .post_shutdown(on_stop)
        .build()
    )


    all_handlers = [
        CommandHandler('start', handlers.start),
        CommandHandler('search', handlers.search),
        CallbackQueryHandler(handlers.select_customer_command, pattern=r"^customer_select:"),
        CallbackQueryHandler(handlers.history_callback, pattern=r"^history:"),
        CallbackQueryHandler(handlers.report_callback, pattern=r"^report:"),
        CommandHandler("summary", handlers.summary),
        CommandHandler("addcustomer", handlers.add_customer_command),
        CommandHandler("addtransaction", handlers.add_transaction_command),
        CommandHandler("delete", handlers.delete_customer_command),
        CommandHandler("rename", handlers.rename_customer_command),
        CommandHandler("changephone", handlers.change_phone_command),
        CommandHandler("undo", handlers.undo),
        CommandHandler("report", handlers.report_command),
    ]

    application.add_handlers(all_handlers)

    # start program
    application.run_polling()
    


if __name__ == '__main__':
    main()