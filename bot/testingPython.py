import asyncio
import aiosqlite

async def main():
    # 1. Connect to an in-memory SQLite database
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row  # Return rows as dict-like objects

        # 2. Create a pseudo table for demonstration
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                salary REAL,
                hired_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 3. Insert pseudo (fake) data
        pseudo_data = [
            {"name": "Alice", "role": "Developer", "salary": 5200.50},
            {"name": "Bob", "role": "Designer", "salary": 4800.00},
            {"name": "Charlie", "role": "Manager", "salary": 6500.75},
            {"name": "Dana", "role": "QA Engineer", "salary": 4300.25},
            {"name": "Eve", "role": "Intern", "salary": 2000.00},
        ]

        await conn.executemany("""
            INSERT INTO employees (name, role, salary)
            VALUES (:name, :role, :salary);
        """, pseudo_data)

        await conn.commit()

        # 4. Query and print pseudo data
        async with asyncio.TaskGroup() as tg:
            t1 = tg.create_task(conn.execute("SELECT * FROM employees RETURNING id;"))
            t2 = tg.create_task(conn.execute("SELECT * FROM employees WHERE role != 'Manager'"))
            
        print("=== Pseudo Employees Table ===")
        print(await t1.result().fetchall()[0])
        print(await t2.result().fetchall())

asyncio.run(main())