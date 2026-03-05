from typing import Optional, Dict
from config import DATABASE_PATH
from services.report_repository import ReportRepository
from services.database_service import DatabaseManager
from utils.types import ReportView

async def fetch_balances_page(
    admin_id: int,
    mode: str,
    limit: int,
    cursor,
) -> Dict:
    db = DatabaseManager(DATABASE_PATH)
    async with db.get_connection() as conn:
        repo = ReportRepository(conn)

        items, next_cursor, has_more = await repo.fetch_balances_page(
            admin_id,
            mode,
            limit,
            cursor,
        )

        return {
            "items": items,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "current_cursor": cursor,
        }

async def fetch_transactions_page(
    customer_id: int,
    admin_id: int,
    limit: int,
    cursor,
) -> Dict:

    db = DatabaseManager(DATABASE_PATH)
    async with db.get_connection() as conn:
        repo = ReportRepository(conn)

        page = await repo.fetch_transactions_page(
            customer_id,
            admin_id,
            limit,
            cursor,
        )

        page["current_cursor"] = cursor
        return page

async def fetch_overall_info(admin_id: int) -> Dict:
    db = DatabaseManager(DATABASE_PATH)
    async with db.get_connection() as conn:
        repo = ReportRepository(conn)
        return await repo.fetch_overall_report(admin_id)