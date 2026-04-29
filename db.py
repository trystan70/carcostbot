"""
Car cost bot DB — v6
JSON file store instead of SQLite — no external dependencies.
"""
import json
import os
from pathlib import Path

DATA_FILE        = os.environ.get("DATA_FILE", "/data/carbot.json")
PETROL_COST      = 3.10
WEEKDAY_RATE     = 3.50
EVENING_RATE     = 2.50
WEEKLY_CAP       = 10.50


def _load() -> dict:
    try:
        return json.loads(Path(DATA_FILE).read_text())
    except Exception:
        return {}


def _save(data: dict):
    p = Path(DATA_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def _day(data: dict, day: str) -> dict:
    if day not in data:
        data[day] = {
            "friend1_morning": 0, "friend1_evening": 0,
            "friend2_morning": 0, "friend2_evening": 0,
            "friend3_morning": 0, "friend3_evening": 0,
            "parking_type": "none", "extra_passengers": 0,
            "skipped": 0, "evening_logged": 0,
        }
    return data[day]


def init(): pass  # no-op, file created on first write


def ensure_day(day: str):
    data = _load()
    _day(data, day)
    _save(data)


def set_trip(day: str, field: str, value: bool):
    data = _load()
    _day(data, day)[field] = 1 if value else 0
    _save(data)


def set_parking_type(day: str, ptype: str):
    data = _load()
    _day(data, day)["parking_type"] = ptype
    _save(data)


def set_extra_passengers(day: str, count: int):
    data = _load()
    _day(data, day)["extra_passengers"] = count
    _save(data)


def set_skipped(day: str, val: bool):
    data = _load()
    _day(data, day)["skipped"] = 1 if val else 0
    _save(data)


def set_evening_logged(day: str):
    data = _load()
    _day(data, day)["evening_logged"] = 1
    _save(data)


def is_skipped(day: str) -> bool:
    return bool(_load().get(day, {}).get("skipped", 0))


def is_evening_logged(day: str) -> bool:
    return bool(_load().get(day, {}).get("evening_logged", 0))


def has_any_data(day: str) -> bool:
    d = _load().get(day, {})
    return bool(d.get("evening_logged", 0)) or bool(d.get("skipped", 0))


def parking_rate(ptype: str) -> float:
    if ptype == "weekday": return WEEKDAY_RATE
    if ptype == "evening": return EVENING_RATE
    return 0.0


def day_summary(day: str) -> dict:
    row = _load().get(day)
    if not row:
        return _empty_day(day)

    f1t     = row["friend1_morning"] + row["friend1_evening"]
    f2t     = row["friend2_morning"] + row["friend2_evening"]
    f3t     = row.get("friend3_morning", 0) + row.get("friend3_evening", 0)
    ext     = row.get("extra_passengers", 0)
    ptype   = row.get("parking_type", "none")
    parking = parking_rate(ptype)
    daily   = parking + PETROL_COST
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

    unit_cost     = daily / pool_units if pool_units > 0 else 0.0
    ex_owes_each  = round(unit_cost, 2)
    ex_owes_total = round(ex_owes_each * ext, 2)

    return {
        "date": day, "parking_type": ptype, "parking_cost": parking,
        "petrol": PETROL_COST, "pool_units": pool_units,
        "friend1_trips": f1t, "friend2_trips": f2t, "friend3_trips": f3t,
        "extra_passengers": ext,
        "f1_park": f1_park, "f2_park": f2_park, "f3_park": f3_park,
        "f1_pet":  f1_pet,  "f2_pet":  f2_pet,  "f3_pet":  f3_pet,
        "ex_owes_each": ex_owes_each, "ex_owes_total": ex_owes_total,
        "unit_cost": round(unit_cost, 4),
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
    f1_wd = f1_ev = f2_wd = f2_ev = f3_wd = f3_ev = 0.0
    f1_pet = f2_pet = f3_pet = 0.0

    for day in days:
        s     = day_summary(day)
        ptype = s["parking_type"]
        if ptype == "weekday":
            f1_wd += s["f1_park"]; f2_wd += s["f2_park"]; f3_wd += s["f3_park"]
        elif ptype == "evening":
            f1_ev += s["f1_park"]; f2_ev += s["f2_park"]; f3_ev += s["f3_park"]
        f1_pet += s["f1_pet"]; f2_pet += s["f2_pet"]; f3_pet += s["f3_pet"]

    def capped(wd, ev):
        return min(wd, WEEKLY_CAP) + min(ev, WEEKLY_CAP)

    f1_pr = f1_wd + f1_ev; f2_pr = f2_wd + f2_ev; f3_pr = f3_wd + f3_ev
    f1_pc = capped(f1_wd, f1_ev)
    f2_pc = capped(f2_wd, f2_ev)
    f3_pc = capped(f3_wd, f3_ev)

    return {
        "friend1": round(f1_pet + f1_pc, 2),
        "friend2": round(f2_pet + f2_pc, 2),
        "friend3": round(f3_pet + f3_pc, 2),
        "f1_pet": round(f1_pet, 2), "f2_pet": round(f2_pet, 2), "f3_pet": round(f3_pet, 2),
        "f1_park_raw": round(f1_pr, 2), "f2_park_raw": round(f2_pr, 2), "f3_park_raw": round(f3_pr, 2),
        "f1_park_capped": round(f1_pc, 2), "f2_park_capped": round(f2_pc, 2), "f3_park_capped": round(f3_pc, 2),
    }
