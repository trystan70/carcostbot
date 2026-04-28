"""
Car cost bot DB — v5

Friends: F1 (Fran), F2 (Lauren), F3 (Noah)
Parking cap: applied automatically to ALL named friends
Extra passengers: pay 1-unit share of main pool cost — do NOT dilute the main pool
"""
import sqlite3
from contextlib import contextmanager

DB_PATH          = "carbot.db"
PETROL_COST      = 3.10
WEEKDAY_RATE     = 3.50
EVENING_RATE     = 2.50
WEEKLY_CAP       = 10.50


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
                date               TEXT PRIMARY KEY,
                friend1_morning    INTEGER DEFAULT 0,
                friend1_evening    INTEGER DEFAULT 0,
                friend2_morning    INTEGER DEFAULT 0,
                friend2_evening    INTEGER DEFAULT 0,
                friend3_morning    INTEGER DEFAULT 0,
                friend3_evening    INTEGER DEFAULT 0,
                parking_type       TEXT    DEFAULT 'none',
                extra_passengers   INTEGER DEFAULT 0,
                skipped            INTEGER DEFAULT 0,
                evening_logged     INTEGER DEFAULT 0
            )
        """)
        cols = [r[1] for r in c.execute("PRAGMA table_info(days)")]
        for col, defn in [
            ("extra_passengers", "INTEGER DEFAULT 0"),
            ("parking_type",     "TEXT DEFAULT 'none'"),
            ("skipped",          "INTEGER DEFAULT 0"),
            ("evening_logged",   "INTEGER DEFAULT 0"),
            ("friend3_morning",  "INTEGER DEFAULT 0"),
            ("friend3_evening",  "INTEGER DEFAULT 0"),
        ]:
            if col not in cols:
                c.execute(f"ALTER TABLE days ADD COLUMN {col} {defn}")


def ensure_day(day: str):
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO days (date) VALUES (?)", (day,))


def set_trip(day: str, field: str, value: bool):
    ensure_day(day)
    with conn() as c:
        c.execute(f"UPDATE days SET {field} = ? WHERE date = ?", (1 if value else 0, day))


def set_parking_type(day: str, ptype: str):
    ensure_day(day)
    with conn() as c:
        c.execute("UPDATE days SET parking_type = ? WHERE date = ?", (ptype, day))


def set_extra_passengers(day: str, count: int):
    ensure_day(day)
    with conn() as c:
        c.execute("UPDATE days SET extra_passengers = ? WHERE date = ?", (count, day))


def set_skipped(day: str, val: bool):
    ensure_day(day)
    with conn() as c:
        c.execute("UPDATE days SET skipped = ? WHERE date = ?", (1 if val else 0, day))


def set_evening_logged(day: str):
    ensure_day(day)
    with conn() as c:
        c.execute("UPDATE days SET evening_logged = 1 WHERE date = ?", (day,))


def is_skipped(day: str) -> bool:
    with conn() as c:
        row = c.execute("SELECT skipped FROM days WHERE date = ?", (day,)).fetchone()
    return bool(row["skipped"]) if row else False


def is_evening_logged(day: str) -> bool:
    with conn() as c:
        row = c.execute("SELECT evening_logged FROM days WHERE date = ?", (day,)).fetchone()
    return bool(row["evening_logged"]) if row else False


def has_any_data(day: str) -> bool:
    with conn() as c:
        row = c.execute("SELECT * FROM days WHERE date = ?", (day,)).fetchone()
    if not row:
        return False
    return bool(row["evening_logged"]) or bool(row["skipped"])


def parking_rate(ptype: str) -> float:
    if ptype == "weekday": return WEEKDAY_RATE
    if ptype == "evening": return EVENING_RATE
    return 0.0


def day_summary(day: str) -> dict:
    with conn() as c:
        row = c.execute("SELECT * FROM days WHERE date = ?", (day,)).fetchone()
    if not row:
        return _empty_day(day)

    cols    = row.keys()
    f1t     = row["friend1_morning"] + row["friend1_evening"]
    f2t     = row["friend2_morning"] + row["friend2_evening"]
    f3t     = (row["friend3_morning"] + row["friend3_evening"]) if "friend3_morning" in cols else 0
    ext     = row["extra_passengers"] or 0
    ptype   = row["parking_type"] or "none"
    parking = parking_rate(ptype)
    daily   = parking + PETROL_COST

    # Main pool: driver (2) + named friends only
    pool_units = 2 + f1t + f2t + f3t

    def named_share(trips, cost):
        if pool_units == 0 or trips == 0 or cost == 0:
            return 0.0
        return round(trips / pool_units * cost, 4)

    f1_park = named_share(f1t, parking)
    f2_park = named_share(f2t, parking)
    f3_park = named_share(f3t, parking)
    f1_pet  = named_share(f1t, PETROL_COST)
    f2_pet  = named_share(f2t, PETROL_COST)
    f3_pet  = named_share(f3t, PETROL_COST)

    # Extras: pay 1 unit of the main pool rate (1 trip, not diluting)
    unit_cost    = daily / pool_units if pool_units > 0 else 0.0
    ex_owes_each = round(unit_cost, 2)
    ex_owes_total = round(ex_owes_each * ext, 2)

    return {
        "date":             day,
        "parking_type":     ptype,
        "parking_cost":     parking,
        "petrol":           PETROL_COST,
        "pool_units":       pool_units,
        "friend1_trips":    f1t,
        "friend2_trips":    f2t,
        "friend3_trips":    f3t,
        "extra_passengers": ext,
        "f1_park":          f1_park,
        "f2_park":          f2_park,
        "f3_park":          f3_park,
        "f1_pet":           f1_pet,
        "f2_pet":           f2_pet,
        "f3_pet":           f3_pet,
        "ex_owes_each":     ex_owes_each,
        "ex_owes_total":    ex_owes_total,
        "unit_cost":        round(unit_cost, 4),
    }


def _empty_day(day=""):
    return {
        "date": day, "parking_type": "none", "parking_cost": 0.0,
        "petrol": 0.0, "pool_units": 2,
        "friend1_trips": 0, "friend2_trips": 0, "friend3_trips": 0,
        "extra_passengers": 0,
        "f1_park": 0.0, "f2_park": 0.0, "f3_park": 0.0,
        "f1_pet":  0.0, "f2_pet":  0.0, "f3_pet":  0.0,
        "ex_owes_each": 0.0, "ex_owes_total": 0.0, "unit_cost": 0.0,
    }


def weekly_totals(days: list) -> dict:
    """
    All friends get the same auto cap on parking.
    Petrol never capped.
    """
    f1_wd = f1_ev = 0.0
    f2_wd = f2_ev = 0.0
    f3_wd = f3_ev = 0.0
    f1_pet = f2_pet = f3_pet = 0.0

    for day in days:
        s     = day_summary(day)
        ptype = s["parking_type"]
        if ptype == "weekday":
            f1_wd += s["f1_park"]
            f2_wd += s["f2_park"]
            f3_wd += s["f3_park"]
        elif ptype == "evening":
            f1_ev += s["f1_park"]
            f2_ev += s["f2_park"]
            f3_ev += s["f3_park"]
        f1_pet += s["f1_pet"]
        f2_pet += s["f2_pet"]
        f3_pet += s["f3_pet"]

    def capped(wd, ev):
        return min(wd, WEEKLY_CAP) + min(ev, WEEKLY_CAP)

    f1_park_raw    = f1_wd + f1_ev
    f2_park_raw    = f2_wd + f2_ev
    f3_park_raw    = f3_wd + f3_ev
    f1_park_capped = capped(f1_wd, f1_ev)
    f2_park_capped = capped(f2_wd, f2_ev)
    f3_park_capped = capped(f3_wd, f3_ev)

    return {
        "friend1":          round(f1_pet + f1_park_capped, 2),
        "friend2":          round(f2_pet + f2_park_capped, 2),
        "friend3":          round(f3_pet + f3_park_capped, 2),
        "f1_pet":           round(f1_pet, 2),
        "f2_pet":           round(f2_pet, 2),
        "f3_pet":           round(f3_pet, 2),
        "f1_park_raw":      round(f1_park_raw, 2),
        "f2_park_raw":      round(f2_park_raw, 2),
        "f3_park_raw":      round(f3_park_raw, 2),
        "f1_park_capped":   round(f1_park_capped, 2),
        "f2_park_capped":   round(f2_park_capped, 2),
        "f3_park_capped":   round(f3_park_capped, 2),
    }
