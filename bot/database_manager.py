import json
import logging
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

import aiosqlite

from bot.helpers import format_date, format_enum_members, normalize_name, normalize_phone
from bot.types import (
    ActionLog,
    ActionType,
    ActionPayload,
    Customer,
    ReportView,
    Transaction,
    TransactionType,
)

class AppError(Exception):
    """Represents an intentional, user-facing application error."""
    pass

class DatabaseManager:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn: aiosqlite.Connection = None
        self.logger = logging.getLogger(__name__)

    async def init_database(self) -> None:
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
        await self.conn.execute(f"""
            CREATE TABLE IF NOT EXISTS action_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                action_type TEXT CHECK(
                    action_type IN ({format_enum_members(ActionType)})
                ),
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
        self.logger.info("Database initialized and tables ensured at %s", self.db_path)

    # -----------------------------------------------------------------------
    # Customer methods
    # -----------------------------------------------------------------------

    async def search_customers(self, query: str, limit: int, admin_id: int) -> List[Dict[str, Any]]:
        """
        returns all customers with names that contain 'query' as a substring
        e.g. query="ali" >> [{"id": 17, "fullname": "Ali Hassan"},  {"id": 42, "fullname": "Ali Omar"}]
        """
        # normalize input
        self.logger.debug("Searching customers for query=%s limit=%s admin_id=%s", query, limit, admin_id)
        query_normalized = normalize_name(query)

        # Execute SQL search
        async with self.conn.execute(
            """
            SELECT id, fullname
            FROM customers
            WHERE (fullname LIKE ? OR phone LIKE ?) AND admin_id = ?
            ORDER BY fullname ASC
            LIMIT ?;
            """,
            (
                f"%{query_normalized}%",
                f"%{query_normalized}%",
                admin_id,
                limit,
            ),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]


    async def add_customer(
        self, fullname: str, phone: Optional[str], admin_id: int,
        with_commit: bool = True, with_logging: bool = True
    ) -> int: #bookmark: [unhandled case] phone = none
        """ Returns customer id  """
        try:
            self.logger.debug("Adding customer fullname=%s admin_id=%s", fullname, admin_id)
            cursor = await self.conn.execute(
                """
                INSERT INTO customers (fullname, phone, admin_id)
                VALUES (?, ?, ?)
                RETURNING id;
                """,
                (fullname, phone, admin_id),
            )
            customer_row = await cursor.fetchone()
            customer_id = customer_row['id']
            if with_logging:
                payload = {
                    'undo-args': {
                        'customer_id': customer_id,
                        'admin_id': admin_id,
                    },
                    'more-info': {},
                }
                await self.add_action_log(ActionType.ADD_CUSTOMER, customer_id, admin_id, payload)

            with_commit and await self.conn.commit()
            self.logger.info(
                "Added customer id=%s fullname=%s admin_id=%s",
                customer_id,
                fullname,
                admin_id,
            )
            return customer_id

        except aiosqlite.IntegrityError as exc:
            await self.conn.rollback()
            self.logger.exception("Failed to add customer %s: %s", fullname, exc)
            raise AppError(
                f"Customer named '{fullname}' already exists"
            ) from exc

        except Exception as exc:
            await self.conn.rollback()
            self.logger.exception("Unexpected error while adding customer %s: %s", fullname, exc)
            raise Exception(f"Unexpected Error: {exc}") from exc
    
    async def get_customer_by_id(self, customer_id: int, admin_id: int) -> Optional[Customer]:
        """Retrieve a customer dict by id."""
        self.logger.debug("Fetching customer id=%s admin_id=%s", customer_id, admin_id)

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
                customer['customer_id'] = customer.pop('id')
                return customer


    async def get_customer_summary(
        self, customer_id: int, admin_id: int
    ) -> Optional[Dict[str, Any]]:

        customer = await self.get_customer_by_id(customer_id, admin_id)
        if customer is None:
            return None

        self.logger.debug(
            "Building summary for customer_id=%s admin_id=%s",
            customer_id,
            admin_id,
        )

        async with asyncio.TaskGroup() as tg:
            totals_task = tg.create_task(
                self.conn.execute(
                    """
                    SELECT
                        TOTAL(CASE WHEN type = 'sale' THEN amount END) AS total_sales,
                        TOTAL(CASE WHEN type = 'payment' THEN amount END) AS total_payments
                    FROM transactions
                    WHERE customer_id = ? AND admin_id = ?;
                    """,
                    (customer_id, admin_id),
                )
            )

            recent_task = tg.create_task(
                self.conn.execute(
                    """
                    SELECT type, amount, created_at
                    FROM transactions
                    WHERE customer_id = ? AND admin_id = ?
                    ORDER BY created_at DESC
                    LIMIT 5;
                    """,
                    (customer_id, admin_id),
                )
            )

        totals_cursor = totals_task.result()
        recent_cursor = recent_task.result()

        totals_row = await totals_cursor.fetchone()
        totals = dict(totals_row) if totals_row else {}

        rows = await recent_cursor.fetchall()

        recent = [
            {
                **dict(row),
                "created_at": format_date(row["created_at"])
            }
            for row in rows
        ]

        return {
            **customer,
            "payments": float(totals.get("total_payments", 0.0)),
            "sales": float(totals.get("total_sales", 0.0)),
            "recent": recent,
        }


    async def delete_customer(
        self, customer_id: int, admin_id: int,
        with_commit: bool = True, with_logging: bool = True
    ) -> Customer:
        try:
            if with_logging:
                customer: Customer = await self.get_customer_by_id(customer_id, admin_id)
                customer_transactions = await self._get_customer_transactions(
                    customer_id,
                    admin_id,
                )
                undo_args: Dict[str, Any] = {}
                undo_args.update(customer)
                undo_args.update({'customer_transactions': customer_transactions})
                payload = {
                    'undo-args': undo_args,
                    'more-info': {},
                }
                await self.add_action_log(
                    ActionType.DELETE_CUSTOMER,
                    customer_id,
                    admin_id,
                    payload,
                    with_commit=False,
                )


            cur = await self.conn.execute("""
                DELETE FROM customers 
                WHERE id = ? AND admin_id = ?
                RETURNING *;
            """, (customer_id, admin_id))
            customer_row = dict(await cur.fetchone())
            if cur.rowcount == 0: raise AppError("Customer is NOT deleted successfully. retry later")
            with_commit and await self.conn.commit()
            self.logger.info(
                "Deleted customer id=%s fullname=%s admin_id=%s",
                customer_id,
                customer_row.get('fullname'),
                admin_id,
            )
            return customer_row

        except AppError:
            await self.conn.rollback()
            raise
        except Exception as exc:
            await self.conn.rollback()
            self.logger.exception(f"{exc}")
            raise Exception(f"Unexpected Error: {exc}") from exc

    async def update_customer_name(
        self, new_name: str, customer_id: int, admin_id: int, with_logging: bool = True
    ) -> Dict[str, Any]:

        customer = await self.get_customer_by_id(customer_id, admin_id)
        old_name = customer['fullname']
        name_change_info = {
            'admin_id': admin_id,
            'customer_id': customer_id,
            'new_name': new_name,
            'old_name': old_name
        }
        try:
            self.logger.debug(
                "Updating customer name id=%s old_name=%s new_name=%s admin=%s",
                customer_id,
                old_name,
                new_name,
                admin_id,
            )
            if with_logging:
                payload = {
                    'undo-args':name_change_info.copy(),
                    'more-info':{}
                }
                await self.add_action_log('rename_customer',customer_id, admin_id, payload, with_commit=False)

            cursor = await self.conn.execute("""
                UPDATE customers SET fullname = ? WHERE id = ? AND admin_id = ? RETURNING balance;
                """, (new_name, customer_id, admin_id))
            customer_row = await cursor.fetchone()
            balance = customer_row['balance']
            await self.conn.commit()
            if cursor.rowcount == 0: raise AppError("Customer is NOT renamed. retry later!")
            name_change_info.update({'balance': balance})
            self.logger.info(
                "Updated customer name id=%s from %s to %s (balance=%s)",
                customer_id,
                old_name,
                new_name,
                balance,
            )
            return name_change_info


        except aiosqlite.IntegrityError as exc:
            raise AppError(
                f"Customer name '{new_name}' already exists"
            ) from exc
        except AppError:
            raise
        except Exception as exc:
            await self.conn.rollback()
            self.logger.exception(f"Unexpected Error: {exc}")
            raise Exception(f"Unexpected Error: {exc}") from exc
    
    async def update_customer_phone(
        self, new_phone: str, customer_id: int, admin_id: int,
        with_logging: bool = True
    ) -> Dict[str, Any]:
        customer = await self.get_customer_by_id(customer_id, admin_id)
        old_phone = customer['phone']
        phone_change = {
            'admin_id': admin_id,
            'customer_id': customer_id,
            'new_phone': new_phone,
            'old_phone': old_phone,
        }
        try:
            self.logger.debug(
                "Updating phone for customer id=%s old_phone=%s new_phone=%s admin=%s",
                customer_id,
                old_phone,
                new_phone,
                admin_id,
            )
            if with_logging:
                payload = {
                    'undo-args': phone_change,
                    'more-info': {}
                }
                await self.add_action_log('change_phone', customer_id, admin_id,payload, with_commit=False)

            cur = await self.conn.execute("""
                UPDATE customers SET phone = ? WHERE id = ? AND admin_id = ? RETURNING fullname,balance;
            """, (new_phone, customer_id, admin_id))
            customer_row = await cur.fetchone()
            fullname = customer_row['fullname']
            balance = customer_row['balance']
            await self.conn.commit()
            if cur.rowcount == 0:   raise AppError("Customer's phone can NOT be changed now. retry later")
            phone_change.update({'fullname': fullname, 'balance': balance})
            self.logger.info(
                "Updated phone for customer id=%s fullname=%s admin=%s",
                customer_id,
                fullname,
                admin_id,
            )
            return phone_change

        except AppError:
            raise
        except Exception as exc:
            await self.conn.rollback()
            self.logger.exception(exc)
            raise Exception(f"Unexpected Error: {exc}") from exc

    async def _get_customer_transactions(self, customer_id: int, admin_id: int) -> List[Transaction]:
        """
        Retrieve all transactions for a specific customer under a specific admin.

        Returns:
            list[dict]: A list of transaction dictionaries, where each dictionary represents
                        a transaction record with column names as keys.
        """
        self.logger.debug(
            "Fetching transactions for customer_id=%s admin_id=%s",
            customer_id,
            admin_id,
        )
        transaction_rows = await self.conn.execute_fetchall(
            """
            SELECT *
            FROM transactions
            WHERE customer_id = ? AND admin_id = ?;
            """,
            (customer_id, admin_id),
        )
        transactions: List[Transaction] = [dict(row) for row in transaction_rows]
        return transactions

    # -----------------------------------------------------------------------
    # Transaction methods
    # -----------------------------------------------------------------------
    async def add_transaction(
        self, amount: float, type_: TransactionType, description: str, customer_id: int, admin_id: int,
        with_commit: bool = True, with_logging: bool = True
    ) -> Dict[str, Any]:
        """Insert transaction and return created transaction as a dict"""
        try:
            self.logger.debug(
                "Adding transaction type=%s amount=%s customer=%s admin=%s",
                type_,
                amount,
                customer_id,
                admin_id,
            )
            if type_ not in (TransactionType.SALE, TransactionType.PAYMENT):
                raise AppError('Invalid transaction type')

            await self._update_balance(amount, type_, customer_id)

            cur = await self.conn.execute("""
                INSERT INTO transactions (amount, type, customer_id, admin_id, description)
                VALUES (?, ?, ?, ?, ?) RETURNING id;
            """, (amount, type_, customer_id, admin_id, description))
            transaction_id = (await cur.fetchone())['id']

            transaction_log = {
                'customer_id': customer_id,
                'admin_id': admin_id,
                'transaction_id': transaction_id,
            }
            if with_logging:
                payload: ActionPayload = {
                    'undo-args': transaction_log,
                    'more-info': {},  # replace empty dict with 'update_customer'
                }
                await self.add_action_log(
                    ActionType.ADD_TRANSACTION,
                    customer_id,
                    admin_id,
                    payload,
                    with_commit=False,
                )  # bookmark: do not store the entire transaction in log...
            if with_commit:
                await self.conn.commit()
            self.logger.info(
                "Added transaction id=%s type=%s amount=%s customer=%s admin=%s",
                transaction_id,
                type_,
                amount,
                customer_id,
                admin_id,
            )
            return transaction_log


        except AppError:
            raise
        except Exception as exc:
            self.logger.exception(str(exc))
            await self.conn.rollback()
            raise Exception(f"Unexpected Error: {exc}") from exc

    async def _restore_transactions(self, customer_transactions: List[Transaction]) -> None:
        self.logger.debug("Restoring %s transactions", len(customer_transactions))
        cur = await self.conn.executemany("""
            INSERT INTO transactions (id, amount, customer_id, admin_id, description, type, created_at)
            VALUES (:id, :amount, :customer_id, :admin_id, :description, :type, :created_at);
        """, customer_transactions)

    async def _delete_transaction_with_id(self, transaction_id: int) -> Dict[str, Any]:
        self.logger.debug("Deleting transaction id=%s", transaction_id)
        cur = await self.conn.execute("""
                DELETE FROM transactions
                WHERE id = ? RETURNING *;
            """, (transaction_id,))
        transaction = dict(await cur.fetchone())
        self.logger.info(
            "Deleted transaction id=%s for customer=%s amount=%s",
            transaction_id,
            transaction.get('customer_id'),
            transaction.get('amount'),
        )
        return transaction

    async def _update_balance(self, amount: float, type_: TransactionType, customer_id: int) -> Dict[str, Any]:
        self.logger.debug(
            "Updating balance for customer=%s type=%s amount=%s",
            customer_id,
            type_,
            amount,
        )
        if type_ == 'payment':
            sign = 1
        elif type_ == 'sale':
            sign = -1
        else:
            raise AppError('invalid transaction type.')
        balance_delta = sign * abs(amount)

        # add new transaction + adjust customer balance
        cursor = await self.conn.execute("""
            UPDATE customers SET balance = balance + ? WHERE id = ? RETURNING balance, fullname;
        """, (balance_delta, customer_id))
        customer_row = await cursor.fetchone()
        updated = dict(customer_row)
        self.logger.info(
            "Updated balance for customer=%s fullname=%s new_balance=%s",
            customer_id,
            updated.get('fullname'),
            updated.get('balance'),
        )
        return updated

    # -----------------------------------------------------------------------
    # Action log methods
    # -----------------------------------------------------------------------
    async def add_action_log(
        self,
        action_type: ActionType,
        customer_id: int,
        admin_id: int,
        action_info: ActionPayload,
        with_commit: bool = True,
    ) -> None:
        payload = json.dumps(action_info)
        self.logger.debug(
            "Inserting action_log action_type=%s customer_id=%s admin_id=%s",
            action_type,
            customer_id,
            admin_id,
        )
        await self.conn.execute(
            """
                INSERT INTO action_logs (action_type, customer_id, admin_id, payload)
                VALUES (?, ?, ?, ?);
            """,
            (action_type, customer_id, admin_id, payload),
        )
        if with_commit:
            await self.conn.commit()
            self.logger.info(
                "Action log inserted: action_type=%s customer_id=%s admin_id=%s",
                action_type,
                customer_id,
                admin_id,
            )

    async def clear_old_logs(self) -> None:
        self.logger.info("Archiving and clearing logs older than 30 days")
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
        self.logger.info("Archived old logs and cleared action_logs table")

    # -----------------------------------------------------------------------
    # Undo methods
    # -----------------------------------------------------------------------
    async def undo_delete_customer(self, customer_id: int, admin_id: int,phone: Optional[str], fullname: str, created_at: str, balance: float, customer_transactions: List[Transaction]) -> Dict[str, Any]:
        self.logger.debug("Undoing delete customer start: id=%s admin=%s", customer_id, admin_id)
        temp_id = await self.add_customer(fullname, phone, admin_id, with_commit=False, with_logging=False)
        cursor = await self.conn.execute(
            """
            UPDATE customers
            SET id = ?, created_at = ?, balance = ?
            WHERE id = ? RETURNING *;
            """,
            (customer_id, created_at, balance, temp_id)
        )
        # restore_transactions && restore_action_logs
        # await self._restore_action_logs()
        await self._restore_transactions(customer_transactions)
        is_restored = cursor.rowcount == 0
        if not is_restored:
            raise AppError("deleted Customer can not be restored")

        customer_row = await cursor.fetchone()
        undo_details = {
            'Full Name': customer_row['fullname'].upper(),
            'Phone': customer_row['phone'],
            'Balance': customer_row['balance'],
        }
        return undo_details

    async def undo_add_customer(self, customer_id: int, admin_id: int) -> Dict[str, Any]:
        customer = await self.delete_customer(customer_id, admin_id, with_commit=True, with_logging=False)
        self.logger.info("Undid add customer id=%s admin=%s", customer_id, admin_id)
        undo_details = {
            'Full Name': customer['fullname'],
            'Phone': customer['phone'],
            'Balance': customer['balance'],
        }
        return undo_details

    async def undo_update_customer_name(self, admin_id: int, customer_id: int, new_name: str, old_name: str) -> Dict[str, str]:
        undo_data = await self.update_customer_name(old_name, customer_id, admin_id, with_logging=False)
        return {
            'Was Renamed to': new_name,
            'Current Name': old_name,
            'with Balance': undo_data['balance']
        }

    async def undo_add_transaction(self, transaction_id: int) -> Dict[str, str]:
        try:
            transaction = await self._delete_transaction_with_id(transaction_id)
            amount, customer_id = transaction['amount'],  transaction['customer_id']
            self.logger.debug("Undoing transaction id=%s amount=%s customer=%s", transaction_id, amount, customer_id)
            type_ = 'payment' if transaction['type'] == 'sale' else 'sale'
            updated_customer = await self._update_balance(amount, type_, customer_id)
            self.logger.info("Undid transaction id=%s for customer=%s new_balance=%s", transaction_id, customer_id, updated_customer['balance'])
            return {
                'Transfer': f"{transaction['amount']} -> <i>{transaction['type']}</i>",
                'For': updated_customer['fullname'],
                'Current Balance': updated_customer['balance']
            }

        except Exception as exc:
            self.logger.exception(str(exc))
            await self.conn.rollback()
            raise Exception(f"Unexpected Error: {exc}") from exc

    async def undo_update_customer_phone(self, admin_id: int, customer_id: int, new_phone: str, old_phone: Optional[str]) -> Dict[str, str]:
        undo_data = await self.update_customer_phone(old_phone, customer_id, admin_id, with_logging=False)
        self.logger.info("Undid phone update for customer=%s admin=%s", customer_id, admin_id)
        return {
            'Phone Was Updated to': new_phone,
            'Current Phone': old_phone,
            'Full Name': undo_data['fullname'],
            'with Balance': undo_data['balance']
        }
    

    async def undo_last_action_for_admin(self, admin_id: int, user_data: Dict[str, Any]) -> str:
        from bot.undo_helpers import execute_undo

        try:
            self.logger.debug("undoing last action for admin=%s", admin_id)
            await self.conn.execute("BEGIN")
            log = await self._fetch_last_log(admin_id)
            if not log:
                raise AppError("no action avaeilable to be undone")
            payload = json.loads(log["payload"])
            feedback_msg = await execute_undo(self, log["action_type"], payload, user_data)
            cur = await self.conn.execute(
                "DELETE FROM action_logs WHERE id = ?;",
                (log["id"],)
            )
            not_updated = cur.rowcount == 0
            if not_updated:
                raise Exception

            await self.conn.commit()
            self.logger.info("Undid for admin=%s action_id=%s", admin_id, log["id"])
            return feedback_msg
        except AppError:
            await self.conn.rollback()
            raise

        except Exception as exc:
            await self.conn.rollback()
            self.logger.exception("Failed to undo last action for admin %s: %s", admin_id, exc)
            raise

    async def _fetch_last_log(self, admin_id: int) -> Optional[ActionLog]:
        self.logger.debug("Fetching last action log for admin=%s", admin_id)
        cur = await self.conn.execute("""
            SELECT * FROM action_logs
            WHERE admin_id = ?
            ORDER BY id DESC
            LIMIT 1;
        """, (admin_id,))
        log_row = await cur.fetchone()
        return None if not log_row else dict(log_row)


    # -----------------------------------------------------------------------
    # Pager-view methods
    # -----------------------------------------------------------------------

    async def fetch_balances_page(
        self,
        mode: ReportView,
        admin_id: int,
        limit: int = 5,
        cursor: Optional[Tuple[float, int]] = None,
    ) -> Dict[str, Any]:
        """
        Fetch a page of customers filtered by balance status using composite
        (balance, id) cursor-based pagination.

        Cursor format:
            (last_balance, last_id)

        Returns:
            {
                "items": List[Dict[str, Any]],
                "next_cursor": Optional[Tuple[float, int]],
                "has_more": bool,
            }
        """

        self.logger.debug(
            "Fetching balances page admin_id=%s mode=%s cursor=%s limit=%s",
            admin_id,
            mode,
            cursor,
            limit,
        )

        # Explicit mode configuration (single source of truth)
        mode_cfg = {
            ReportView.DUE_CUSTOMERS: {
                "balance_op": "<",
                "order": "balance ASC, id ASC",
                "cursor_cmp": "balance > ? OR (balance = ? AND id > ?)",
            },
            ReportView.OVERPAID_CUSTOMERS: {
                "balance_op": ">",
                "order": "balance DESC, id ASC",
                "cursor_cmp": "balance < ? OR (balance = ? AND id > ?)",
            },
        }

        try:
            cfg = mode_cfg[mode]
        except KeyError:
            raise ValueError(f"Unsupported report view: {mode}") from None

        sql = f"""
            SELECT *
            FROM customers
            WHERE admin_id = ?
            AND balance {cfg["balance_op"]} 0
            {{cursor_clause}}
            ORDER BY {cfg["order"]}
            LIMIT ?;
        """

        params: list[Any] = [admin_id]
        cursor_clause = ""

        if cursor is not None:
            last_balance, last_id = cursor
            cursor_clause = f"AND ({cfg['cursor_cmp']})"
            params.extend([last_balance, last_balance, last_id])

        query = sql.format(cursor_clause=cursor_clause)
        params.append(limit + 1)

        rows = await self.conn.execute_fetchall(query, tuple(params))

        items = [dict(row) for row in rows[:limit]]
        has_more = len(rows) > limit

        next_cursor = None
        if items:
            last = items[-1]
            next_cursor = f"{last["balance"]}, {last["id"]}"

        return {
            "items": items,
            "next_cursor": next_cursor,
            "has_more": has_more,
        }


    async def fetch_transactions_page(
        self,
        customer_id: int,
        admin_id: int,
        limit: int = 5,
        before_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Fetch a page of transactions for a customer using an id-based cursor.

        Returns a dict with keys: items (List[Transaction]), next_cursor (Optional[int]),
        has_more (bool).
        """
        self.logger.debug(
            "Fetching transactions page for customer=%s admin=%s before_id=%s limit=%s",
            customer_id,
            admin_id,
            before_id,
            limit,
        )
        if before_id is None:
            query = """
                SELECT * FROM transactions
                WHERE customer_id = ? AND admin_id = ?
                ORDER BY id DESC
                LIMIT ?;
            """
            params = (customer_id, admin_id, limit + 1)
        else:
            query = """
                SELECT * FROM transactions
                WHERE customer_id = ? AND admin_id = ? AND id < ?
                ORDER BY id DESC
                LIMIT ?;
            """
            params = (customer_id, admin_id, before_id, limit + 1)

        rows = await self.conn.execute_fetchall(query, params)
        rows = [dict(r) for r in rows]
        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]
        next_cursor = rows[-1]['id'] if rows else None
        return {"items": rows, "next_cursor": next_cursor, "has_more": has_more}

    async def fetch_action_logs_page(
        self,
        admin_id: int,
        limit: int = 5,
        before_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Fetch a page of action logs for an admin using an id-based cursor.

        Returns a dict with keys: items (List[ActionLog]), next_cursor (Optional[int]), has_more (bool).
        """
        self.logger.debug("Fetching action logs page for admin=%s before_id=%s limit=%s", admin_id, before_id, limit)
        if before_id is None:
            query = """
                SELECT * FROM action_logs
                WHERE admin_id = ?
                ORDER BY id DESC
                LIMIT ?;
            """
            params = (admin_id, limit + 1)
        else:
            query = """
                SELECT * FROM action_logs
                WHERE admin_id = ? AND id < ?
                ORDER BY id DESC
                LIMIT ?;
            """
            params = (admin_id, before_id, limit + 1)

        rows = await self.conn.execute_fetchall(query, params)
        rows = [dict(r) for r in rows]
        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]
        next_cursor = rows[-1]['id'] if rows else None
        return {"items": rows, "next_cursor": next_cursor, "has_more": has_more}

    async def close(self) -> None:
        """Close DB connection."""
        if self.conn is not None:
            try:
                await self.conn.close()
            finally:
                self.conn = None