"""Core database manager - initialization and undo coordination."""
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

import aiosqlite
from utils.types import ActionLog, ActionType, ActionPayload, Customer, Transaction, ReportView
from utils.utils import format_enum_members

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Represents an intentional, user-facing application error."""
    pass


class DatabaseManager:
    """Manages database connection, schema initialization, and undo operations."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn: aiosqlite.Connection = None
        self.logger = logging.getLogger(__name__)

    async def init_database(self) -> None:
        """Create required tables if they don't exist."""
        self.conn = await aiosqlite.connect(self.db_path)

        await self.conn.execute("PRAGMA foreign_keys = ON;")
        
        # Create customers table
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
        
        # Create transactions table
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
        
        # Create action logs table
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
        
        # Create action logs archive table
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS action_logs_archive
            AS SELECT * FROM action_logs WHERE 0;
        """)

        await self.conn.commit()
        self.conn.row_factory = aiosqlite.Row
        self.logger.info("Database initialized and tables ensured at %s", self.db_path)

    # -----------------------------------------------------------------------
    # Undo coordination methods
    # -----------------------------------------------------------------------

    async def undo_last_action_for_admin(self, admin_id: int, user_data: Dict[str, Any]) -> str:
        """Orchestrate undo of the last action for an admin."""
        from services.action_log_repository import ActionLogRepository
        from services.undo_service import execute_undo

        try:
            self.logger.debug("Undoing last action for admin=%s", admin_id)
            await self.conn.execute("BEGIN")
            
            action_log_repo = ActionLogRepository(self.conn)
            log = await action_log_repo.fetch_last_log(admin_id)
            
            if not log:
                raise AppError("No action available to be undone")
            
            payload = log["payload"]
            feedback_msg = await execute_undo(self, log["action_type"], payload, user_data)
            
            await self.conn.execute(
                "DELETE FROM action_logs WHERE id = ?;",
                (log["id"],)
            )
            
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

    async def undo_delete_customer(
        self,
        customer_id: int,
        admin_id: int,
        phone: Optional[str],
        fullname: str,
        created_at: str,
        balance: float,
        customer_transactions: List[Transaction],
    ) -> Dict[str, Any]:
        """Undo customer deletion (restore customer and transactions)."""
        from services.customer_repository import CustomerRepository
        from services.transaction_repository import TransactionRepository

        self.logger.debug("Undoing delete customer: id=%s admin=%s", customer_id, admin_id)
        
        customer_repo = CustomerRepository(self.conn)
        transaction_repo = TransactionRepository(self.conn)
        
        # Create temporary customer to get next ID
        temp_id = await customer_repo.add_customer(fullname, phone, admin_id)
        
        # Update to use original ID
        await self.conn.execute(
            """
            UPDATE customers
            SET id = ?, created_at = ?, balance = ?
            WHERE id = ?;
            """,
            (customer_id, created_at, balance, temp_id),
        )
        
        # Restore transactions
        await transaction_repo.restore_transactions(customer_transactions)
        
        await self.conn.commit()
        
        undo_details = {
            "Full Name": fullname.upper(),
            "Phone": phone,
            "Balance": balance,
        }
        return undo_details

    async def undo_add_customer(self, customer_id: int, admin_id: int) -> Dict[str, Any]:
        """Undo customer addition (delete customer)."""
        from services.customer_repository import CustomerRepository

        self.logger.debug("Undoing add customer: id=%s admin=%s", customer_id, admin_id)
        
        customer_repo = CustomerRepository(self.conn)
        customer = await customer_repo.get_customer_by_id(customer_id, admin_id)
        
        await customer_repo.delete_customer(customer_id, admin_id)
        
        undo_details = {
            "Full Name": customer["fullname"],
            "Phone": customer["phone"],
            "Balance": customer["balance"],
        }
        return undo_details

    async def undo_update_customer_name(
        self,
        admin_id: int,
        customer_id: int,
        new_name: str,
        old_name: str,
    ) -> Dict[str, str]:
        """Undo customer name update."""
        from services.customer_repository import CustomerRepository

        self.logger.debug(
            "Undoing name update: customer=%s old=%s new=%s",
            customer_id,
            old_name,
            new_name,
        )
        
        customer_repo = CustomerRepository(self.conn)
        await customer_repo.update_customer_name(old_name, customer_id, admin_id)
        
        return {
            "Was Renamed to": new_name,
            "Current Name": old_name,
        }

    async def undo_add_transaction(self, transaction_id: int) -> Dict[str, str]:
        """Undo transaction addition (delete transaction)."""
        from services.transaction_repository import TransactionRepository

        self.logger.debug("Undoing transaction: id=%s", transaction_id)
        
        transaction_repo = TransactionRepository(self.conn)
        result = await transaction_repo.delete_transaction_with_id(transaction_id)
        
        return {
            "Transfer": result["Removed Transaction"],
            "Customer id": result["Customer id"],
        }

    async def undo_update_customer_phone(
        self,
        admin_id: int,
        customer_id: int,
        new_phone: str,
        old_phone: Optional[str],
    ) -> Dict[str, str]:
        """Undo customer phone update."""
        from services.customer_repository import CustomerRepository

        self.logger.debug(
            "Undoing phone update: customer=%s old=%s new=%s",
            customer_id,
            old_phone,
            new_phone,
        )
        
        customer_repo = CustomerRepository(self.conn)
        await customer_repo.update_customer_phone(old_phone, customer_id, admin_id)
        
        return {
            "Phone Was Updated to": new_phone,
            "Current Phone": old_phone,
        }

    async def close(self) -> None:
        """Close database connection."""
        if self.conn is not None:
            try:
                await self.conn.close()
            finally:
                pass
