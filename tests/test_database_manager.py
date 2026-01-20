import json
from datetime import datetime, timedelta

import pytest

from bot.database_manager import DatabaseManager, AppError
from bot.types import TransactionType, ActionType


@pytest.mark.asyncio
async def test_add_customer_duplicate_raises(tmp_path):
    db = DatabaseManager(str(tmp_path / "dup.db"))
    await db.init_database()
    await db.add_customer("John Doe", "1234567890", admin_id=1)
    with pytest.raises(AppError):
        await db.add_customer("John Doe", "0000000000", admin_id=1)
    await db.close()


@pytest.mark.asyncio
async def test_search_customers_returns_results(tmp_path):
    db = DatabaseManager(str(tmp_path / "search.db"))
    await db.init_database()
    await db.add_customer("Alice One", "111", admin_id=1)
    await db.add_customer("Alice Two", "222", admin_id=1)
    results = await db.search_customers("alice", limit=10, admin_id=1)
    assert len(results) == 2
    await db.close()


@pytest.mark.asyncio
async def test_get_customer_summary_totals_and_recent(tmp_path):
    db = DatabaseManager(str(tmp_path / "summary.db"))
    await db.init_database()
    cid = await db.add_customer("Sam Smith", "999", admin_id=2)
    await db.add_transaction(100.0, TransactionType.SALE, "sale1", cid, 2)
    await db.add_transaction(40.0, TransactionType.PAYMENT, "pay1", cid, 2)
    summary = await db.get_customer_summary(cid, 2)
    assert summary["sales"] == pytest.approx(100.0)
    assert summary["payments"] == pytest.approx(40.0)
    assert isinstance(summary["recent"], list)
    await db.close()


@pytest.mark.asyncio
async def test_add_payment_updates_balance(tmp_path):
    db = DatabaseManager(str(tmp_path / "payment.db"))
    await db.init_database()
    cid = await db.add_customer("Pay User", "000", admin_id=3)
    await db.add_transaction(50.0, TransactionType.PAYMENT, "payment", cid, 3)
    customer = await db.get_customer_by_id(cid, 3)
    assert customer["balance"] == pytest.approx(50.0)
    await db.close()


@pytest.mark.asyncio
async def test_undo_add_transaction(tmp_path):
    db = DatabaseManager(str(tmp_path / "undo_tx.db"))
    await db.init_database()
    cid = await db.add_customer("Undo TX", "100", admin_id=4)
    await db.add_transaction(30.0, TransactionType.SALE, "sale", cid, 4)
    before = await db.get_customer_by_id(cid, 4)
    assert before["balance"] == pytest.approx(-30.0)
    res = await db.undo_last_action_for_admin(4, {})
    assert isinstance(res, str)
    after = await db.get_customer_by_id(cid, 4)
    assert after["balance"] == pytest.approx(0.0)
    await db.close()


@pytest.mark.asyncio
async def test_update_name_and_undo(tmp_path):
    db = DatabaseManager(str(tmp_path / "rename.db"))
    await db.init_database()
    cid = await db.add_customer("Old Name", "321", admin_id=5)
    await db.update_customer_name("New Name", cid, admin_id=5)
    c = await db.get_customer_by_id(cid, 5)
    assert c["fullname"] == "New Name"
    await db.undo_last_action_for_admin(5, {})
    c2 = await db.get_customer_by_id(cid, 5)
    assert c2["fullname"] == "Old Name"
    await db.close()


@pytest.mark.asyncio
async def test_delete_and_undo_restores_customer_and_transactions(tmp_path):
    db = DatabaseManager(str(tmp_path / "delete_undo.db"))
    await db.init_database()
    cid = await db.add_customer("Del User", "555", admin_id=6)
    await db.add_transaction(10.0, TransactionType.SALE, "t1", cid, 6)
    await db.delete_customer(cid, admin_id=6)
    # restoring via undo_last_action_for_admin should bring customer back
    res = await db.undo_last_action_for_admin(6, {})
    assert isinstance(res, str)
    restored = await db.get_customer_by_id(cid, 6)
    assert restored is not None
    await db.close()


@pytest.mark.asyncio
async def test_clear_old_logs_archives(tmp_path):
    db = DatabaseManager(str(tmp_path / "archive.db"))
    await db.init_database()
    payload = json.dumps({"undo-args": {}})
    # insert an old log (1970) directly
    await db.conn.execute(
        "INSERT INTO action_logs (admin_id, customer_id, action_type, payload, created_at) VALUES (?, ?, ?, ?, ?);",
        (7, 1, ActionType.ADD_CUSTOMER.value, payload, "1970-01-01 00:00:00"),
    )
    await db.conn.commit()
    await db.clear_old_logs()
    cur = await db.conn.execute("SELECT COUNT(*) as c FROM action_logs_archive;")
    row = await cur.fetchone()
    assert row["c"] >= 1
    await db.close()