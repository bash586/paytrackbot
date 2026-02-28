import asyncio
import logging
import os
from dotenv import load_dotenv
from telegram.ext import (
    ApplicationBuilder, filters, ConversationHandler, CallbackQueryHandler, CommandHandler, PicklePersistence, PersistenceInput, MessageHandler
)
import handlers
from services.database_service import DatabaseManager
from config import RECEIVE_ARGS, ASK_QUERY, DATABASE_PATH, RECEIVE_QUERY

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

    # CallbackQueryHandler(handlers.cancel_search, pattern=r"^cancel_waiting_search_query:$")
    all_handlers = [
        CommandHandler('start', handlers.start),
        CallbackQueryHandler(handlers.select_customer_command, pattern=r"^customer_select:"),
        CallbackQueryHandler(handlers.report_callback, pattern=r"^report:"),
        CommandHandler("summary", handlers.summary),
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.COMMAND & filters.Regex(r"^/addtransaction"),
                    handlers.ask_command_args,
                ),
                MessageHandler(
                    filters.COMMAND & filters.Regex(r"^/addcustomer"),
                    handlers.ask_command_args,
                ),
            ],
            states = {
                ASK_QUERY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.ask_search_query)
                ],
                RECEIVE_QUERY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_search_query)
                ],
                RECEIVE_ARGS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_command_args)
                ],
            },
            fallbacks=[
                CallbackQueryHandler(handlers.end_conversation, pattern=r"^end_conversation$"),
            ],
        ),
        CommandHandler("addtransaction", handlers.add_transaction_command),
        CommandHandler("delete", handlers.delete_customer_command),
        CommandHandler("rename", handlers.rename_customer_command),
        CommandHandler("changephone", handlers.change_phone_command),
        CommandHandler("undo", handlers.undo),
        CommandHandler("report", handlers.report_command),
        ConversationHandler(
            entry_points=[
                CallbackQueryHandler(handlers.ask_search_query, pattern=r"^wait_search_query:"),
                CommandHandler("search", handlers.ask_search_query),
                ],
            states={
                RECEIVE_QUERY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_search_query)
                ]
            },
            fallbacks=[
                CallbackQueryHandler(handlers.end_conversation, pattern=r"^end_conversation$"),
            ],
        ),
    ]
    application.add_handlers(all_handlers)

    # start program
    application.run_polling()

if __name__ == '__main__':
    main()