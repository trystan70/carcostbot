"""
Car cost bot DB — v4

Parking / petrol split logic:
  total_units = 2 (driver) + f1_trips + f2_trips + extras * 2

  Named friends pay proportional share of ACTUAL parking:
    f1_park = f1_trips / total_units * parking
    f2_park = f2_trips / total_units * parking

  Extra passengers pay proportional share of VIRTUAL £8 parking:
    ex_park_each = 2 / total_units * EXTRA_PARK_BASIS  (×count for total)

  Everyone (incl. extras) shares petrol pool equally by units:
    each_pet = trips / total_units * PETROL_COST

  Result: extras being present reduces named friends' costs (larger denominator),
  but extras pay as if parking was £8 regardless of actual rate.

  Cap applies to F1 parking (auto). F2 cap is optional (user prompted).
  Petrol never capped.
"""
import sqlite3
from contextlib import contextmanager

DB_PATH          = "carbot.db"
PETROL_COST      = 2.92
WEEKDAY_RATE     = 3.50
EVENING_RATE     = 2.50
WEEKLY_CAP       = 10.50
EXTRA_PARK_BASIS = 8.00   # virtual parking rate used to charge extra passengers


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
                extra_passengers   INTEGER DEFAULT 0,
                skipped            INTEGER DEFAULT 0
            )
        """)
        cols = [r[1] for r in c.execute("PRAGMA table_info(days)")]
        for col, defn in [
            ("extra_passengers", "INTEGER DEFAULT 0"),
            ("parking_type",     "TEXT DEFAULT 'none'"),
            ("skipped",          "INTEGER DEFAULT 0"),
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


def is_skipped(day: str) -> bool:
    with conn() as c:
        row = c.execute("SELECT skipped FROM days WHERE date = ?", (day,)).fetchone()
    return bool(row["skipped"]) if row else False


def parking_rate(ptype: str) -> float:
    if ptype == "weekday": return WEEKDAY_RATE
    if ptype == "evening": return EVENING_RATE
    return 0.0


def day_summary(day: str) -> dict:
    with conn() as c:
        row = c.execute("SELECT * FROM days WHERE date = ?", (day,)).fetchone()
    if not row:
        return _empty_day(day)

    f1t     = row["friend1_morning"] + row["friend1_evening"]
    f2t     = row["friend2_morning"] + row["friend2_evening"]
    ext     = row["extra_passengers"] or 0
    ptype   = row["parking_type"] or "none"
    parking = parking_rate(ptype)

    # Unified unit pool — extras included, reduces named friends' shares
    total_units = 2 + f1t + f2t + (ext * 2)

    def named_share(trips, cost):
        """Named person's share of a cost based on actual rate."""
        if total_units == 0 or trips == 0 or cost == 0:
            return 0.0
        return round(trips / total_units * cost, 4)

    def extra_share(virtual_cost):
        """Each extra passenger's share using their virtual rate, both trips."""
        if total_units == 0 or ext == 0:
            return 0.0
        return round(2 / total_units * virtual_cost, 4)  # per extra, both ways

    # Named friends: actual parking, shared petrol
    f1_park = named_share(f1t, parking)
    f2_park = named_share(f2t, parking)
    f1_pet  = named_share(f1t, PETROL_COST)
    f2_pet  = named_share(f2t, PETROL_COST)

    # Extras: virtual £8 parking + shared petrol (per extra person)
    ex_park_each = extra_share(EXTRA_PARK_BASIS)
    ex_pet_each  = extra_share(PETROL_COST)
    ex_owes_each = round(ex_park_each + ex_pet_each, 2)

    return {
        "date":             day,
        "parking_type":     ptype,
        "parking_cost":     parking,
        "petrol":           PETROL_COST,
        "total_units":      total_units,
        "friend1_trips":    f1t,
        "friend2_trips":    f2t,
        "extra_passengers": ext,
        "f1_park":          f1_park,
        "f2_park":          f2_park,
        "f1_pet":           f1_pet,
        "f2_pet":           f2_pet,
        "ex_park_each":     ex_park_each,
        "ex_pet_each":      ex_pet_each,
        "ex_owes_each":     ex_owes_each,
        "ex_owes_total":    round(ex_owes_each * ext, 2),
    }


def _empty_day(day=""):
    return {
        "date": day, "parking_type": "none", "parking_cost": 0.0,
        "petrol": 0.0, "total_units": 2,
        "friend1_trips": 0, "friend2_trips": 0, "extra_passengers": 0,
        "f1_park": 0.0, "f2_park": 0.0, "f1_pet": 0.0, "f2_pet": 0.0,
        "ex_park_each": 0.0, "ex_pet_each": 0.0,
        "ex_owes_each": 0.0, "ex_owes_total": 0.0,
    }


def weekly_totals(days: list) -> dict:
    f1_wd_park = f1_ev_park = 0.0
    f2_wd_park = f2_ev_park = 0.0
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

    f1_park_raw    = f1_wd_park + f1_ev_park
    f1_park_capped = min(f1_wd_park, WEEKLY_CAP) + min(f1_ev_park, WEEKLY_CAP)
    f2_park_raw    = f2_wd_park + f2_ev_park
    f2_park_capped = min(f2_wd_park, WEEKLY_CAP) + min(f2_ev_park, WEEKLY_CAP)
    f2_over_cap    = (f2_park_raw > f2_park_capped) and f2_had_trips

    return {
        "friend1":         round(f1_pet + f1_park_capped, 2),
        "friend2_raw":     round(f2_pet + f2_park_raw,    2),
        "friend2_capped":  round(f2_pet + f2_park_capped, 2),
        "f1_pet":          round(f1_pet,         2),
        "f1_park_raw":     round(f1_park_raw,    2),
        "f1_park_capped":  round(f1_park_capped, 2),
        "f2_pet":          round(f2_pet,          2),
        "f2_park_raw":     round(f2_park_raw,     2),
        "f2_park_capped":  round(f2_park_capped,  2),
        "f2_over_cap":     f2_over_cap,
        "f2_cap_saving":   round(f2_park_raw - f2_park_capped, 2),
    }
