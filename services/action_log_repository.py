"""Data access layer for action logging and audit trail."""
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from utils.types import ActionLog, ActionType, ActionPayload

logger = logging.getLogger(__name__)


class ActionLogRepository:
    """Handles all action logging and audit trail operations."""
    
    def __init__(self, conn):
        """Initialize with database connection."""
        self.conn = conn
    
    async def add_action_log(
        self,
        action_type: ActionType,
        admin_id: int,
        customer_id: int,
        payload: ActionPayload,
    ) -> int:
        """Log an action for audit trail and undo functionality."""
        logger.debug(
            "Adding action log: action_type=%s admin_id=%s customer_id=%s",
            action_type.value,
            admin_id,
            customer_id,
        )
        
        try:
            cursor = await self.conn.execute(
                """
                INSERT INTO action_logs (action_type, admin_id, customer_id, payload)
                VALUES (?, ?, ?, ?);
                """,
                (action_type.value, admin_id, customer_id, json.dumps(payload)),
            )
            # await self.conn.commit()
            action_id = cursor.lastrowid
            
            logger.info(
                "Action log inserted: action_type=%s customer_id=%s admin_id=%s",
                action_type.value,
                customer_id,
                admin_id,
            )
            return action_id
        except Exception as exc:
            # await self.conn.rollback()
            raise exc

    async def fetch_last_log(self, admin_id: int) -> Optional[ActionLog]:
        """Get the last action log for an admin."""
        async with self.conn.execute(
            """
            SELECT id, action_type, admin_id, customer_id, payload, created_at
            FROM action_logs
            WHERE admin_id = ?
            ORDER BY id DESC LIMIT 1;
            """,
            (admin_id,),
        ) as cursor:
            log = await cursor.fetchone()

        if not log:
            logger.debug("No action logs found for admin_id=%s", admin_id)
            return None

        return {
            "id": log["id"],
            "action_type": log["action_type"],
            "admin_id": log["admin_id"],
            "customer_id": log["customer_id"],
            "payload": json.loads(log["payload"]),
            "created_at": log["created_at"],
        }

    async def delete_action_log(self, action_id: int) -> None:
        """Delete an action log entry."""

        await self.conn.execute(
            "DELETE FROM action_logs WHERE id = ?;",
            (action_id,),
        )

    async def clear_old_logs(self, days: int = 30) -> None:
        """Clear action logs older than specified days."""
        logger.debug("Clearing action logs older than %d days", days)
        
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

        try:
            # Archive old logs
            await self.conn.execute(
                """
                INSERT INTO action_logs_archive (id, action_type, admin_id, customer_id, payload, created_at)
                SELECT id, action_type, admin_id, customer_id, payload, created_at
                FROM action_logs
                WHERE created_at < ?;
                """,
                (cutoff_date,),
            )

            # Delete from main table
            await self.conn.execute(
                "DELETE FROM action_logs WHERE created_at < ?;",
                (cutoff_date,),
            )

            await self.conn.commit()
            logger.info("Cleared action logs older than %s", cutoff_date)
        except Exception as exc:
            await self.conn.rollback()
            raise exc