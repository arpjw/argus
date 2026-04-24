import os

import aiosqlite

from argus import config

DB_PATH = config.DB_PATH


async def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS synthesis_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                regime TEXT,
                confidence REAL,
                narrative TEXT NOT NULL,
                flag_count INTEGER,
                trigger_type TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS anomaly_flags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER REFERENCES synthesis_runs(id),
                timestamp TEXT NOT NULL,
                instrument TEXT,
                flag_type TEXT,
                severity TEXT,
                detail TEXT
            )
        """)
        await db.commit()


async def save_run(timestamp, regime, confidence, narrative, flag_count, trigger_type) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO synthesis_runs (timestamp, regime, confidence, narrative, flag_count, trigger_type) VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, regime, confidence, narrative, flag_count, trigger_type),
        )
        await db.commit()
        return cursor.lastrowid


async def save_flags(run_id: int, flags: list):
    if not flags:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT INTO anomaly_flags (run_id, timestamp, instrument, flag_type, severity, detail) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    run_id,
                    f.timestamp.isoformat() if hasattr(f.timestamp, "isoformat") else str(f.timestamp),
                    f.instrument,
                    f.type,
                    f.severity,
                    f.description,
                )
                for f in flags
            ],
        )
        await db.commit()


async def get_recent_runs(limit: int = 50) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM synthesis_runs ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
