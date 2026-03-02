"""
Car cost bot DB — v3

Changes from v2:
  - Petrol is fixed at PETROL_COST per driving day (not user-inputted)
  - Parking and petrol split separately; cap never applies to petrol
  - Friend 2 parking cap is optional (flagged, not automatic)
  - extra_passengers column: other one-off passengers for a day
"""
import sqlite3
from contextlib import contextmanager

DB_PATH      = "carbot.db"
PETROL_COST  = 2.92   # fixed daily petrol cost
WEEKDAY_RATE = 3.50
EVENING_RATE = 2.50
WEEKLY_CAP   = 10.50


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
                parking_type       TEXT    DEFAULT 'none',
                extra_passengers   INTEGER DEFAULT 0
            )
        """)
        # migrate old schemas
        cols = [r[1] for r in c.execute("PRAGMA table_info(days)")]
        if "extra_passengers" not in cols:
            c.execute("ALTER TABLE days ADD COLUMN extra_passengers INTEGER DEFAULT 0")
        if "parking_type" not in cols:
            c.execute("ALTER TABLE days ADD COLUMN parking_type TEXT DEFAULT 'none'")
        # drop old cost/fuel columns if present (can't drop in SQLite, just ignore)


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


def parking_rate(ptype: str) -> float:
    if ptype == "weekday": return WEEKDAY_RATE
    if ptype == "evening": return EVENING_RATE
    return 0.0


def day_summary(day: str) -> dict:
    with conn() as c:
        row = c.execute("SELECT * FROM days WHERE date = ?", (day,)).fetchone()
    if not row:
        return _empty_day(day)

    f1t = row["friend1_morning"] + row["friend1_evening"]
    f2t = row["friend2_morning"] + row["friend2_evening"]
    ext = row["extra_passengers"] or 0
    ptype   = row["parking_type"] or "none"
    parking = parking_rate(ptype)

    # Units: driver=2, each friend/extra=1 per trip
    # Extra passengers are assumed to take the full day (2 units each) — adjust if needed
    total_units = 2 + f1t + f2t + (ext * 2)

    def split_cost(cost):
        if total_units == 0 or cost == 0:
            return 0.0, 0.0, 0.0
        u = cost / total_units
        return round(f1t * u, 4), round(f2t * u, 4), round(ext * 2 * u, 4)

    f1_park, f2_park, ex_park = split_cost(parking)
    f1_pet,  f2_pet,  ex_pet  = split_cost(PETROL_COST)

    return {
        "date":             day,
        "parking_type":     ptype,
        "parking_cost":     parking,
        "petrol":           PETROL_COST,
        "total_units":      total_units,
        "friend1_trips":    f1t,
        "friend2_trips":    f2t,
        "extra_passengers": ext,
        # per-component shares (uncapped)
        "f1_park":          f1_park,
        "f2_park":          f2_park,
        "ex_park":          ex_park,
        "f1_pet":           f1_pet,
        "f2_pet":           f2_pet,
        "ex_pet":           ex_pet,
        # extra total (park + petrol share)
        "extra_owes":       round(ex_park + ex_pet, 2),
    }


def _empty_day(day=""):
    return {
        "date": day, "parking_type": "none", "parking_cost": 0.0,
        "petrol": 0.0, "total_units": 2,
        "friend1_trips": 0, "friend2_trips": 0, "extra_passengers": 0,
        "f1_park": 0.0, "f2_park": 0.0, "ex_park": 0.0,
        "f1_pet":  0.0, "f2_pet":  0.0, "ex_pet":  0.0,
        "extra_owes": 0.0,
    }


def weekly_totals(days: list) -> dict:
    """
    Returns full weekly breakdown.
    Cap applies to F1 parking only (auto).
    F2: returns both uncapped and capped parking — bot decides which to use.
    Petrol is never capped for anyone.
    """
    f1_wd_park = f1_ev_park = 0.0   # weekday / evening parking for F1
    f2_wd_park = f2_ev_park = 0.0   # same for F2 (for optional cap check)
    f1_pet = f2_pet = 0.0
    f2_had_trips = False

    for day in days:
        s     = day_summary(day)
        ptype = s["parking_type"]
        if s["friend2_trips"] > 0:
            f2_had_trips = True
        if ptype == "weekday":
            f1_wd_park += s["f1_park"]
            f2_wd_park += s["f2_park"]
        elif ptype == "evening":
            f1_ev_park += s["f1_park"]
            f2_ev_park += s["f2_park"]
        f1_pet += s["f1_pet"]
        f2_pet += s["f2_pet"]

    # F1: auto-capped
    f1_park_raw    = f1_wd_park + f1_ev_park
    f1_park_capped = min(f1_wd_park, WEEKLY_CAP) + min(f1_ev_park, WEEKLY_CAP)

    # F2: always raw; caller decides
    f2_park_raw    = f2_wd_park + f2_ev_park
    f2_park_capped = min(f2_wd_park, WEEKLY_CAP) + min(f2_ev_park, WEEKLY_CAP)
    f2_over_cap    = (f2_park_raw > f2_park_capped) and f2_had_trips

    return {
        # totals using raw F2 (default)
        "friend1":         round(f1_pet + f1_park_capped, 2),
        "friend2_raw":     round(f2_pet + f2_park_raw,    2),
        "friend2_capped":  round(f2_pet + f2_park_capped, 2),
        # breakdown
        "f1_pet":          round(f1_pet,        2),
        "f1_park_raw":     round(f1_park_raw,   2),
        "f1_park_capped":  round(f1_park_capped,2),
        "f2_pet":          round(f2_pet,         2),
        "f2_park_raw":     round(f2_park_raw,    2),
        "f2_park_capped":  round(f2_park_capped, 2),
        # flag: should we prompt the user about capping F2?
        "f2_over_cap":     f2_over_cap,
        "f2_cap_saving":   round(f2_park_raw - f2_park_capped, 2),
    }
