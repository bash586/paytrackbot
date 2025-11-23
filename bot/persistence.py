import aiosqlite
import json
from telegram.ext import BasePersistence

class CustomPersistence(BasePersistence):

        def __init__(self, db_path):
            super().__init__(store_user_data=True, store_chat_data=True, store_bot_data=False, store_conversations=True)
            self.path = db_path
            self._setup() # bookmark1: consider wrapping this method in a coroutine

        async def _setup(self):
            async with aiosqlite.connect(self.path) as db:
                async with db.cursor() as cur:

                    await cur.execute("PRAGMA foreign_keys = ON;")
                    # bookmark
                    # await cur.execute("""CREATE TABLE IF NOT EXISTS user_data (user_id INTEGER PRIMARY KEY, data TEXT)""")
                    # await cur.execute("""CREATE TABLE IF NOT EXISTS conversations (name TEXT, key TEXT, state TEXT, PRIMARY KEY(name, key))""")

                    await cur.execute("""
                    CREATE TABLE IF NOT EXISTS admins (
                        name TEXT,
                        telegram_id INTEGER PRIMARY KEY UNIQUE
                    )STRICT;
                    """)

                    await cur.execute("""
                    CREATE TABLE IF NOT EXISTS customers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fullname TEXT UNIQUE NOT NULL,
                        phone TEXT UNIQUE,
                        admin INTEGER REFERENCES admins(telegram_id) ON DELETE CASCADE,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )STRICT;
                    """)

                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS transactions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            amount REAL NOT NULL,
                            type TEXT CHECK(type IN ('sale', 'payment')) NOT NULL,
                            customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
                            admin INTEGER REFERENCES admins(telegram_id) ON DELETE CASCADE,
                            description TEXT,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )STRICT;
                    """)
                    await db.commit()

        # ---------- Load Methods ----------
        # def get_user_data(self):
        #     cur = self.conn.cursor() # bookmark2: invalid line (there is no self.conn)
        #     cur.execute("SELECT user_id, data FROM user_data")
        #     return {uid: json.loads(data) for uid, data in cur.fetchall()}

        # def get_chat_data(self):
        #     cur = self.conn.cursor() # bookmark2: invalid line (there is no self.conn)
        #     cur.execute("SELECT chat_id, data FROM chat_data")
        #     return {cid: json.loads(data) for cid, data in cur.fetchall()}

        # def get_bot_data(self):
        #     pass

        # def get_conversations(self, name):
        #     cur = self.conn.cursor()
        #     cur.execute("SELECT key, state FROM conversations WHERE name=?", (name,))
        #     return {k: json.loads(s) for k, s in cur.fetchall()}

        # # ---------- Update Methods ----------
        # def update_user_data(self, user_id, data):
        #     cur = self.conn.cursor()
        #     cur.execute("REPLACE INTO user_data (user_id, data) VALUES (?, ?)", (user_id, json.dumps(data)))
        #     self.conn.commit()

        # def update_chat_data(self, chat_id, data):
        #     cur = self.conn.cursor()
        #     cur.execute("REPLACE INTO chat_data (chat_id, data) VALUES (?, ?)", (chat_id, json.dumps(data)))
        #     self.conn.commit()

        # def update_bot_data(self, data):
        #     pass

        # def update_conversation(self, name, key, new_state):
        #     cur = self.conn.cursor()
        #     cur.execute("REPLACE INTO conversations (name, key, state) VALUES (?, ?, ?)",
        #                 (name, key, json.dumps(new_state)))
        #     self.conn.commit()

        # def flush(self):
        #     self.conn.commit()