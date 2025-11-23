import asyncio
from datetime import datetime
from typing import Optional
import aiosqlite
import json
from telegram.ext import BasePersistence

import aiosqlite
from typing import Any, Optional, List
import logging

from bot.helpers import normalize_fullname, normalize_name, normalize_phone

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: aiosqlite.Connection = None
        self.logger = logging.getLogger(__name__)

    async def init_database(self):
        """Create required tables if they don't exist."""
        
        self.conn = await aiosqlite.connect(self.db_path)

        await self.conn.execute("PRAGMA foreign_keys = ON;")
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fullname TEXT UNIQUE NOT NULL COLLATE NOCASE,
                phone TEXT,
                admin_id INTEGER,
                balance REAL DEFAULT 0.0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            ) STRICT;
        """)
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY,
                amount REAL NOT NULL,
                type TEXT DEFAULT 'sale' CHECK(type IN ('sale', 'payment')),
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                admin_id INTEGER NOT NULL,
                description TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )STRICT;
        """)
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS action_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                action_type TEXT CHECK(action_type IN ('change_phone', 'add_customer', 'add_transaction', 'delete_customer', 'rename_customer')),
                payload TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )STRICT;
        """)

        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS action_logs_archive
            AS SELECT * FROM action_logs WHERE 0;
        """)

        await self.conn.commit()
        self.conn.row_factory = aiosqlite.Row

    #  CUSTOMER Methods

    async def search_customers(self, query: str, limit: int, admin_id: int) -> list[dict[str, str]]:
        """
        returns all customers with names that contain 'query' as a substring
        e.g. query="ali" >> [{"id": 17, "fullname": "Ali Hassan"},  {"id": 42, "fullname": "Ali Omar"}]
        """
        # normalize input
        query_normalized = normalize_name(query)

        # Execute SQL search
        async with self.conn.execute("""
            SELECT id, fullname
            FROM customers
            WHERE (fullname LIKE ? OR phone LIKE ?) AND admin_id = ?
            ORDER BY fullname ASC
            LIMIT ?;
        """, (f"%{query_normalized}%", f"%{query_normalized}%", admin_id, limit)) as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]

    async def add_customer(self, fullname: str, phone: Optional[str], admin_id: int) -> int:
        """
        Insert a new customer record and return its generated ID.
        """
        try:
            cursor = await self.conn.execute(
                """
                INSERT INTO customers (fullname, phone, admin_id, balance)
                VALUES (?, ?, ?, ?)
                RETURNING id;
                """,
                (fullname, phone, admin_id, 0.0),
            )
            row = await cursor.fetchone()
            await self.conn.commit()

            return row

        except aiosqlite.IntegrityError as err:
            raise aiosqlite.IntegrityError(
                f"Customer named '{fullname}' already exists"
            ) from err

    async def get_customer_by_id(self, customer_id: int, admin_id: int) -> Optional[dict]:
        """Retrieve a customer dict by id."""

        async with self.conn.execute(
            """
            SELECT id, fullname, phone, balance, created_at
            From customers
            WHERE id = ? AND admin_id = ?;
            """, (customer_id, admin_id)    
        ) as cur:
            row = await cur.fetchone()
            if row:
                customer = dict(row)
                customer['fullname'] = customer.get('fullname')
                return customer

    async def get_customer_summary(self, customer_id: int, admin_id: int) -> dict | None:

        customer_data = dict()
        customer = await self.get_customer_by_id(customer_id, admin_id)

        if not customer:
            return None

        customer_data.update(customer)

        # get transactions details
        async with asyncio.TaskGroup() as tg:

            totals_task = tg.create_task(self.conn.execute("""
                SELECT TOTAL(CASE WHEN type = 'sale' THEN amount ELSE 0.0 END) as total_sales,
                TOTAL(CASE WHEN type = 'payment' THEN amount ELSE 0.0 END) as total_payments
                FROM transactions
                WHERE customer_id = ? AND admin_id = ?;
                """, (customer_id, admin_id)))
            last_actions_task = tg.create_task(self.conn.execute("""
                SELECT type, amount, created_at
                FROM transactions
                WHERE customer_id = ? AND admin_id = ?
                ORDER BY created_at DESC
                LIMIT 5;
                """ , (customer_id, admin_id)))
        totals_task, last_actions_task  = totals_task.result(), last_actions_task.result()

        totals_dict = dict(await totals_task.fetchone())
        total_payments = totals_dict.get("total_payments", 0)
        total_sales = totals_dict.get("total_sales", 0)

        def map_func(item):
            item = dict(item)
            item['created_at'] = datetime.strptime(item['created_at'], '%Y-%m-%d %H:%M:%S').strftime('%H:%M%p • %d %b %Y')
            return item
        fetched_actions = await last_actions_task.fetchall()
        last_actions = list(map(map_func,fetched_actions))

        customer_data.update({
            'payments': float(total_payments),
            'sales': float(total_sales),
            'recent': last_actions,
        })

        return customer_data

    async def get_customer_transactions(self, customer_id: int, admin_id: int):
        return await self.conn.execute_fetchall("""
            SELECT *
            FROM transactions
            WHERE customer_id = ? AND admin_id = ?;
        """, (customer_id, admin_id))

    async def delete_customer(self, customer_id: int, admin_id: int, with_logging):

        try:
            if with_logging:
                logging_info = await self.get_customer_by_id(customer_id, admin_id)
                customer_transactions = await self.get_customer_transactions(customer_id, admin_id)
                logging_info.update({'customer_transactions': customer_transactions})
                await self.add_action_log('delete_customer', customer_id, admin_id,logging_info, False)

            cur = await self.conn.execute("""
                DELETE FROM customers WHERE id = ? AND admin_id = ?;
            """, (customer_id, admin_id))

            await self.conn.commit()
            return cur.rowcount

        except Exception as exc:
            await self.conn.rollback()
            self.logger.warning(str(exc))
            raise

    async def rename_customer(
        self, new_name: str, customer_id: int, admin_id: int,
        with_logging=True, logging_info: dict = None
    ):

        try:
            cursor = await self.conn.execute("""
                UPDATE customers SET fullname = ? WHERE id = ? AND admin_id = ?;
                """, (new_name, customer_id, admin_id))
            if with_logging:
                customer = await self.get_customer_by_id(customer_id, admin_id)
                old_name = customer['fullname']
                await self.add_action_log('rename_customer',customer_id, admin_id, {'old_name': old_name}, with_commit=False)

            await self.conn.commit()
            return cursor.rowcount

        except aiosqlite.IntegrityError as exc:
            raise aiosqlite.IntegrityError(
                f"Customer name '{new_name}' already exists"
            ) from exc
        except Exception as exc:
            self.conn.rollback()
            self.logger.warning(str(exc))
            raise

    async def change_customer_phone(
        self, new_phone: str, customer_id: int, admin_id: int,
        with_logging=True
    ):
        try:
            if with_logging:
                customer = await self.get_customer_by_id(customer_id, admin_id)
                old_phone = customer['phone']
                await self.add_action_log('change_phone', customer_id, admin_id,{'old_phone': old_phone}, False)

            cur = await self.conn.execute("""
                UPDATE customers SET phone = ? WHERE id = ? AND admin_id = ?;
            """, (new_phone, customer_id, admin_id))
            await self.conn.commit()
            return cur.rowcount
        except Exception:
            await self.conn.rollback()
            raise

    # TRANSACTION Methods
    async def add_transaction(self, amount: float, type_: str, description: str, customer_id: int, admin_id: int) -> int:
        """Insert transaction and return its id."""
        if type_ not in ('sale', 'payment'):
            raise ValueError('Invalid transaction type')

        sign = 1 if type_ == 'payment' else -1
        balance_delta = sign * abs(amount)

        # add new transaction + adjust customer balance
        await self.conn.execute("""
            UPDATE customers SET balance = balance + ? WHERE id = ?;
        """, (balance_delta, customer_id))
        cur = await self.conn.execute("""
            INSERT INTO transactions (amount, type, customer_id, admin_id, description)
            VALUES (?, ?, ?, ?, ?) RETURNING id, amount, description;
        """, (amount, type_, customer_id, admin_id, description))
        transaction = await cur.fetchone()

        await self.conn.commit()

        return transaction

    async def list_transactions(self, customer_id: int) -> List[dict]:
        """Return all transactions for a customer."""

    # ACTION_LOG Methods
    async def add_action_log(self, action_type: str, customer_id: int, admin_id: int, action_info: dict, with_commit: bool = True):
        payload = json.dumps(action_info)
        await self.conn.execute("""
                INSERT INTO action_logs (action_type, customer_id, admin_id, payload)
                VALUES (?, ?, ?, ?);
            """, (action_type, customer_id, admin_id, payload))
        if with_commit:
            await self.conn.commit()

    async def clear_old_logs(self):
        async with (await self.conn.cursor()) as cur:
            # archive old logs
            await cur.execute("""
                    INSERT INTO action_logs_archive
                    SELECT * FROM action_logs
                    WHERE created_at < datetime('now', '-30 day');
            """)
            # delete from logs table
            await cur.execute("""
                DELETE FROM action_logs
                WHERE created_at < datetime('now', '-30 day');
            """)
        await self.conn.commit()
    async def undo_last_action(self):
        cur = await self.conn.execute("""
            SELECT * FROM action_logs
            WHERE admin_id = ?
            ORDER BY id DESC
            LIMIT 1;
        """)
        log = await cur.fetchone()
        await self.conn.execute("DELETE FROM action_logs WHERE id = ?", (log['id'],))

        await self.conn.commit()

        return log
    async def close(self) -> None:
        """Close DB connection."""
        if self.conn is not None:
            try:
                await self.conn.close()
            finally:
                self.conn = None