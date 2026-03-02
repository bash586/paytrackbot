"""Core database manager - initialization and undo coordination."""
from contextlib import asynccontextmanager
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
        self.logger = logging.getLogger(__name__)

    async def init_database(self) -> None:
        """Create required tables if they don't exist."""

        async with self.get_connection() as conn:
            # Create customers table
            await conn.execute("""
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
            await conn.execute("""
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
            await conn.execute(f"""
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
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS action_logs_archive
                AS SELECT * FROM action_logs WHERE 0;
            """)

            await conn.commit()
        self.logger.info("Database initialized and tables ensured at %s", self.db_path)
    @asynccontextmanager
    async def get_connection(self):
        conn = await aiosqlite.connect(self.db_path)
        await conn.execute("PRAGMA foreign_keys = ON;")
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()