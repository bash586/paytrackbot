"""Data access layer for report and analytics operations."""
import logging
from typing import List, Dict, Any, Tuple, Optional
from utils.types import ReportView

logger = logging.getLogger(__name__)


class ReportRepository:
    """Handles all report and analytics database operations."""
    
    def __init__(self, conn):
        """Initialize with database connection."""
        self.conn = conn
    
    async def fetch_balances_page(
        self,
        admin_id: int,
        report_view: ReportView,
        limit: int = 5,
        cursor: Optional[Tuple[float, int]] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[Tuple[float, int]], bool]:
        """Fetch paginated customers sorted by balance (due or overpaid)."""
        logger.debug(
            "Fetching %s page: admin_id=%s limit=%s cursor=%s",
            report_view,
            admin_id,
            limit,
            cursor,
        )

        if report_view == ReportView.DUE_CUSTOMERS:
            query = """
                SELECT id, fullname, balance
                FROM customers
                WHERE admin_id = ? AND balance < 0
            """
            params = [admin_id]
            if cursor:
                query += " AND balance > ?"
                params.append(cursor[0])
            query += " ORDER BY balance ASC LIMIT ?"
            params.append(limit + 1)
        elif report_view == ReportView.OVERPAID_CUSTOMERS:
            query = """
                SELECT id, fullname, balance
                FROM customers
                WHERE admin_id = ? AND balance > 0
            """
            params = [admin_id]
            if cursor:
                query += " AND balance < ?"
                params.append(cursor[0])
            query += " ORDER BY balance DESC LIMIT ?"
            params.append(limit + 1)
        else:
            raise ValueError(f"Unknown report view: {report_view}")

        async with self.conn.execute(query, params) as cursor_db:
            rows = await cursor_db.fetchall()

        items = [
            {
                "customer_id": row["id"],
                "fullname": row["fullname"],
                "balance": row["balance"],
            }
            for row in rows[:limit]
        ]

        has_more = len(rows) > limit
        next_cursor = (rows[limit]["balance"], 0) if has_more else None

        logger.debug("Fetched %d items, has_more=%s", len(items), has_more)
        return items, next_cursor, has_more

    async def fetch_transactions_page(
        self,
        customer_id: int,
        admin_id: int,
        limit: int = 5,
        cursor_value: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Fetch paginated transactions for a customer."""
        logger.debug(
            "Fetching transactions: customer_id=%s admin_id=%s limit=%s cursor=%s",
            customer_id,
            admin_id,
            limit,
            cursor_value,
        )

        query = """
            SELECT id, amount, type, customer_id, admin_id, description, created_at
            FROM transactions
            WHERE customer_id = ? AND admin_id = ?
        """
        params = [customer_id, admin_id]

        if cursor_value:
            query += " AND id < ?"
            params.append(cursor_value)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit + 1)

        async with self.conn.execute(query, params) as cursor_db:
            rows = await cursor_db.fetchall()

        items = [
            {
                "id": row["id"],
                "amount": row["amount"],
                "type": row["type"],
                "customer_id": row["customer_id"],
                "admin_id": row["admin_id"],
                "description": row["description"],
                "created_at": row["created_at"],
            }
            for row in rows[:limit]
        ]

        has_more = len(rows) > limit
        next_cursor = rows[limit]["id"] if has_more else None

        logger.debug("Fetched %d transactions, has_more=%s", len(items), has_more)

        return {
            "items": items,
            "next_cursor": next_cursor,
            "has_more": has_more,
        }

    async def fetch_overall_report(self, admin_id: int) -> Dict[str, Any]:
        """Fetch overall summary statistics for all customers."""
        logger.debug("Fetching overall report for admin_id=%s", admin_id)

        async with self.conn.execute(
            """
            SELECT 
                COUNT(*) as total_customers,
                SUM(CASE WHEN balance < 0 THEN 1 ELSE 0 END) as due_customers,
                SUM(CASE WHEN balance > 0 THEN 1 ELSE 0 END) as overpaid_customers,
                COALESCE(SUM(balance), 0) as total_balance
            FROM customers
            WHERE admin_id = ?;
            """,
            (admin_id,),
        ) as cursor:
            stats = await cursor.fetchone()

        async with self.conn.execute(
            "SELECT COUNT(*) as total_transactions FROM transactions WHERE admin_id = ?;",
            (admin_id,),
        ) as cursor:
            trans_count = await cursor.fetchone()

        report = {
            "total_customers": stats["total_customers"] or 0,
            "due_customers": stats["due_customers"] or 0,
            "overpaid_customers": stats["overpaid_customers"] or 0,
            "total_balance": stats["total_balance"] or 0.0,
            "total_transactions": trans_count["total_transactions"] or 0,
        }

        logger.debug("Overall report: %s", report)
        return report
