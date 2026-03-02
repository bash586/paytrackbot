"""Data access layer for customer operations."""
import logging
from typing import List, Dict, Any, Optional
from services.database_service import AppError
from utils.types import ActionType, Customer
from utils.utils import normalize_name
from aiosqlite import IntegrityError
logger = logging.getLogger(__name__)


class CustomerRepository:
    """Handles all customer-related database operations."""
    
    def __init__(self, conn):
        """Initialize with database connection."""
        self.conn = conn

    async def search_customers(self, query: str, limit: int, admin_id: int) -> List[Dict[str, Any]]:
        """Search customers by name or phone."""
        logger.debug("Searching customers for query=%s limit=%s admin_id=%s", query, limit, admin_id)
        query_normalized = normalize_name(query)

        async with self.conn.execute(
            """
            SELECT id, fullname
            FROM customers
            WHERE (fullname LIKE ? OR phone LIKE ?) AND admin_id = ?
            ORDER BY fullname ASC
            LIMIT ?;
            """,
            (f"%{query_normalized}%", f"%{query}%", admin_id, limit),
        ) as cursor:
            customers = await cursor.fetchall()

        if not customers:
            logger.debug("No customers found matching query=%s", query_normalized)
            return []

        return [
            {"id": customer["id"], "fullname": customer["fullname"]}
            for customer in customers
        ]

    async def update_customer(
        self, cur_id: int, new_id: int, created_at: str, balance: float
    ):
        await self.conn.execute(
            """
            UPDATE customers
            SET id = ?, created_at = ?, balance = ?
            WHERE id = ?;
            """,
            (cur_id, created_at, balance, new_id),
        )

    async def add_customer(
        self, fullname: str, phone: str, admin_id: int
    ) -> int:
        """Add a new customer to the database."""
        try:
            cursor = await self.conn.execute(
                """
                INSERT INTO customers (fullname, phone, admin_id)
                VALUES (?, ?, ?);
                """,
                (fullname, phone, admin_id),
            )

            customer_id = cursor.lastrowid
            return customer_id
        except IntegrityError as exc:
            raise AppError(
                f"Customer named '{fullname}' already exists"
            ) from exc


    async def get_customer_by_id(self, customer_id: int, admin_id: int) -> Optional[Customer]:
        """Fetch customer by ID."""
        async with self.conn.execute(
            "SELECT id, fullname, phone, balance FROM customers WHERE id = ? AND admin_id = ?;",
            (customer_id, admin_id),
        ) as cursor:
            customer = await cursor.fetchone()

        if not customer:
            raise Exception(f"Customer {customer_id} not found")

        return {
            "customer_id": customer["id"],
            "fullname": customer["fullname"],
            "phone": customer["phone"],
            "balance": customer["balance"],
        }

    async def get_customer_summary(self, customer_id: int, admin_id: int) -> Dict[str, Any]:
        """Get comprehensive customer summary with recent transactions."""
        customer = await self.get_customer_by_id(customer_id, admin_id)
        
        # Get recent transactions
        async with self.conn.execute(
            """
            SELECT id, amount, type, description, created_at
            FROM transactions
            WHERE customer_id = ? AND admin_id = ?
            ORDER BY created_at DESC
            LIMIT 5;
            """,
            (customer_id, admin_id),
        ) as cursor:
            transactions = await cursor.fetchall()

        # Calculate totals
        async with self.conn.execute(
            """
            SELECT 
                COALESCE(SUM(CASE WHEN type = 'payment' THEN amount ELSE 0 END), 0) as total_payments,
                COALESCE(SUM(CASE WHEN type = 'sale' THEN amount ELSE 0 END), 0) as total_sales
            FROM transactions
            WHERE customer_id = ? AND admin_id = ?;
            """,
            (customer_id, admin_id),
        ) as cursor:
            totals = await cursor.fetchone()

        recent_transactions = [
            {
                "id": t["id"],
                "amount": t["amount"],
                "type": t["type"],
                "description": t["description"],
                "created_at": t["created_at"],
            }
            for t in transactions
        ]

        return {
            "customer_id": customer["customer_id"],
            "fullname": customer["fullname"],
            "phone": customer["phone"],
            "balance": customer["balance"],
            "payments": totals["total_payments"],
            "sales": totals["total_sales"],
            "recent": recent_transactions,
        }

    async def delete_customer(self, customer_id: int, admin_id: int) -> None:
        """Delete a customer and all related transactions."""
        logger.debug("Deleting customer id=%s", customer_id)

        await self.conn.execute(
            "DELETE FROM transactions WHERE customer_id = ? AND admin_id = ?;",
            (customer_id, admin_id),
        )
        await self.conn.execute(
            "DELETE FROM customers WHERE id = ? AND admin_id = ?;",
            (customer_id, admin_id),
        )
        logger.info("Deleted customer id=%s", customer_id)

    async def update_customer_name(
        self, new_name: str, customer_id: int, admin_id: int
    ) -> Dict[str, str]:
        """Update customer name."""
        logger.debug("Updating customer name: customer_id=%s new_name=%s", customer_id, new_name)

        # Get old name
        async with self.conn.execute(
            "SELECT fullname FROM customers WHERE id = ? AND admin_id = ?;",
            (customer_id, admin_id),
        ) as cursor:
            customer = await cursor.fetchone()

        if not customer:
            raise Exception(f"Customer with id:{customer_id} not found")

        old_name = customer["fullname"]

        try:
            await self.conn.execute(
                "UPDATE customers SET fullname = ? WHERE id = ? AND admin_id = ?;",
                (new_name, customer_id, admin_id),
            )
            logger.info("Updated customer name: id=%s old=%s new=%s", customer_id, old_name, new_name)

        except IntegrityError as exc:
            raise AppError(f"A customer with the name {new_name} already exists.")

        return {"Old Name": old_name, "New Name": new_name, "Current Name": new_name}

    async def update_customer_phone(
        self, new_phone: str, customer_id: int, admin_id: int
    ) -> Dict[str, str]:
        """Update customer phone."""
        logger.debug("Updating customer phone: customer_id=%s new_phone=%s", customer_id, new_phone)
        
        # Get old phone
        async with self.conn.execute(
            "SELECT phone FROM customers WHERE id = ? AND admin_id = ?;",
            (customer_id, admin_id),
        ) as cursor:
            customer = await cursor.fetchone()

        if not customer:
            raise Exception(f"Customer {customer_id} not found")

        old_phone = customer["phone"]

        await self.conn.execute(
            "UPDATE customers SET phone = ? WHERE id = ? AND admin_id = ?;",
            (new_phone, customer_id, admin_id),
        )
        logger.info("Updated customer phone: id=%s", customer_id)

        return {"Old Phone": old_phone, "New Phone": new_phone}
