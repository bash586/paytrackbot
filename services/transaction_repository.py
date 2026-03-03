"""Data access layer for transaction operations."""
import logging
from typing import List, Dict, Any, Optional
from config import DATABASE_PATH
from services.database_service import AppError, DatabaseManager
from utils.types import Transaction, TransactionType

logger = logging.getLogger(__name__)


class TransactionRepository:
    """Handles all transaction-related database operations."""
    
    def __init__(self, conn):
        """Initialize with database connection."""
        self.conn = conn
    
    async def add_transaction(
        self,
        amount: float,
        type_: str,
        description: str,
        customer_id: int,
        admin_id: int,
    ) -> int:
        """Add a new transaction and update customer balance."""
        logger.debug(
            "Adding transaction: amount=%s type=%s customer_id=%s admin_id=%s",
            amount,
            type_,
            customer_id,
            admin_id,
        )

        try:
            async with await self.conn.execute(
                """
                INSERT INTO transactions (amount, type, customer_id, admin_id, description)
                VALUES (?, ?, ?, ?, ?);
                """,
                (amount, type_, customer_id, admin_id, description),
            ) as cur:
                transaction_id = cur.lastrowid

            # Update balance
            balance_change = amount if type_ == "payment" else -amount
            await self.conn.execute(
                "UPDATE customers SET balance = balance + ? WHERE id = ?;",
                (balance_change, customer_id),
            )

            logger.info(
                "Added transaction id=%s amount=%s type=%s customer_id=%s",
                transaction_id,
                amount,
                type_,
                customer_id,
            )
            return transaction_id
        except Exception as exc:
            raise exc

    async def get_customer_transactions(
        self, customer_id: int, admin_id: int
    ) -> List[Transaction]:
        """Get all transactions for a customer."""
        async with self.conn.execute(
            """
            SELECT id, amount, type, customer_id, admin_id, description, created_at
            FROM transactions
            WHERE customer_id = ? AND admin_id = ?
            ORDER BY created_at DESC;
            """,
            (customer_id, admin_id),
        ) as cursor:
            transactions = await cursor.fetchall()

        return [
            {
                "id": t["id"],
                "amount": t["amount"],
                "type": t["type"],
                "customer_id": t["customer_id"],
                "admin_id": t["admin_id"],
                "description": t["description"],
                "created_at": t["created_at"],
            }
            for t in transactions
        ]

    async def delete_transaction_with_id(self, transaction_id: int) -> Dict[str, Any]:
        """Delete a transaction by ID and reverse balance update."""
        logger.debug("Deleting transaction id=%s", transaction_id)
        
        # Get transaction details
        db = DatabaseManager(DATABASE_PATH)
        async with self.conn.execute(
            "SELECT customer_id, amount, type FROM transactions WHERE id = ?;",
            (transaction_id,),
        ) as cur:
            transaction = await cur.fetchone()

        if not transaction:
            raise AppError(f"Transaction {transaction_id} not found")

        customer_id = transaction["customer_id"]
        amount = transaction["amount"]
        trans_type = transaction["type"]

        await self.conn.execute(
            "DELETE FROM transactions WHERE id = ?;",
            (transaction_id,),
        )
        # update customer's balance
        balance_change = -(amount if trans_type == "payment" else -amount)
        await self.conn.execute(
            "UPDATE customers SET balance = balance + ? WHERE id = ?;",
            (balance_change, customer_id),
        )

        logger.info("Deleted transaction id=%s", transaction_id)
        return {
            "Removed Transaction": f"{amount} {trans_type}",
            "Customer id": customer_id,
        }

    async def update_balance(self, amount: float, type_: str, customer_id: int) -> Dict[str, Any]:
        """Update customer balance based on transaction."""
        balance_change = amount if type_ == "payment" else -amount
        
        try:
            await self.conn.execute(
                "UPDATE customers SET balance = balance + ? WHERE id = ?;",
                (balance_change, customer_id),
            )
            await self.conn.commit()
        except Exception as exc:
            await self.conn.rollback()
            raise exc

        async with self.conn.execute(
            "SELECT balance FROM customers WHERE id = ?;",
            (customer_id,),
        ) as cursor:
            customer = await cursor.fetchone()

        return {
            "Remaining Balance": customer["balance"],
            "Paid Amount": amount if type_ == "payment" else 0,
        }

    async def restore_transactions(self, customer_transactions: List[Transaction]) -> None:
        """Restore previously deleted transactions."""
        logger.debug("Restoring %d transactions", len(customer_transactions))
        
        for transaction in customer_transactions:
            await self.conn.execute(
                """
                INSERT INTO transactions (
                    id, amount, type,
                    customer_id, admin_id,
                    description, created_at
                )
                VALUES (
                    :id, :amount, :type,
                    :customer_id, :admin_id,
                    :description, :created_at
                );
                """,
                transaction,
            )
        logger.info("Restored %d transactions", len(customer_transactions))
