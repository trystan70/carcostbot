"""
SQLite database layer for car cost bot.

Schema:
  days(date TEXT PRIMARY KEY,
       friend1_morning INT, friend1_evening INT,
       friend2_morning INT, friend2_evening INT,
       cost REAL)
"""
import sqlite3
from contextlib import contextmanager

DB_PATH = "carbot.db"


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS days (
                date             TEXT PRIMARY KEY,
                friend1_morning  INTEGER DEFAULT 0,
                friend1_evening  INTEGER DEFAULT 0,
                friend2_morning  INTEGER DEFAULT 0,
                friend2_evening  INTEGER DEFAULT 0,
                cost             REAL    DEFAULT 0.0
            )
        """)


def ensure_day(day: str):
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO days (date) VALUES (?)", (day,))


def set_trip(day: str, field: str, value: bool):
    ensure_day(day)
    with conn() as c:
        c.execute(f"UPDATE days SET {field} = ? WHERE date = ?", (1 if value else 0, day))


def set_cost(day: str, cost: float):
    ensure_day(day)
    with conn() as c:
        c.execute("UPDATE days SET cost = ? WHERE date = ?", (cost, day))


def day_summary(day: str) -> dict:
    with conn() as c:
        row = c.execute("SELECT * FROM days WHERE date = ?", (day,)).fetchone()
    if not row:
        return {"friend1_trips": 0, "friend2_trips": 0, "friend1_owes": 0.0, "friend2_owes": 0.0}

    f1_trips = row["friend1_morning"] + row["friend1_evening"]
    f2_trips = row["friend2_morning"] + row["friend2_evening"]
    cost     = row["cost"] or 0.0

    # you always count as 2 units (both ways)
    total_units = 2 + f1_trips + f2_trips
    unit_cost   = cost / total_units if total_units > 0 else 0.0

    return {
        "friend1_trips": f1_trips,
        "friend2_trips": f2_trips,
        "friend1_owes":  round(f1_trips * unit_cost, 2),
        "friend2_owes":  round(f2_trips * unit_cost, 2),
    }


def weekly_totals(days: list[str]) -> dict:
    f1_total = 0.0
    f2_total = 0.0
    for day in days:
        s = day_summary(day)
        f1_total += s["friend1_owes"]
        f2_total += s["friend2_owes"]
    return {"friend1": round(f1_total, 2), "friend2": round(f2_total, 2)}
