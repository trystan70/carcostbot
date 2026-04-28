import os
import logging
from datetime import date, timedelta, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CallbackQueryHandler,
    CommandHandler, MessageHandler, filters, ContextTypes,
)
import pytz
import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
TOKEN        = os.environ["TELEGRAM_TOKEN"]
YOUR_CHAT    = int(os.environ["YOUR_CHAT_ID"])
FRIEND_1     = os.environ.get("FRIEND_1_NAME", "Fran")
FRIEND_2     = os.environ.get("FRIEND_2_NAME", "Lauren")
FRIEND_3     = os.environ.get("FRIEND_3_NAME", "Noah")
TIMEZONE     = os.environ.get("TIMEZONE", "Europe/London")
PAYMENT_LINK = os.environ.get("PAYMENT_LINK", "")
TZ           = pytz.timezone(TIMEZONE)
DAY_NAMES    = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAYS     = tuple(range(5))


# ── Helpers ────────────────────────────────────────────────────────────────────
def fmt(v):  return f"£{v:.2f}"

def pay_link(amount):
    return (f"\n💸 Pay here: {PAYMENT_LINK} (send {fmt(amount)})"
            if PAYMENT_LINK else f"\n💸 Please send me {fmt(amount)}")

def yn_kb(yes_cb, no_cb):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data=yes_cb),
        InlineKeyboardButton("❌ No",  callback_data=no_cb),
    ]])

def current_week_days():
    today = date.today()
    mon   = today - timedelta(days=today.weekday())
    return [(mon + timedelta(days=i)).isoformat() for i in range(7)]

def last_week_monday():
    today = date.today()
    return (today - timedelta(days=today.weekday() + 7)).isoformat()

def week_days_for_monday(monday_str: str):
    mon = date.fromisoformat(monday_str)
    return [(mon + timedelta(days=i)).isoformat() for i in range(7)]

def day_label(day_str: str) -> str:
    return date.fromisoformat(day_str).strftime("%a %-d %b")


# ── Morning / Evening starters ─────────────────────────────────────────────────
async def start_morning(bot, day):
    db.ensure_day(day)
    await bot.send_message(
        chat_id=YOUR_CHAT,
        text=f"🌅 *Morning check-in!*\nDid *{FRIEND_1}* get a lift in this morning?",
        parse_mode="Markdown",
        reply_markup=yn_kb(f"morn_f1_yes_{day}", f"morn_f1_no_{day}")
    )

async def start_evening(bot, day):
    db.ensure_day(day)
    await bot.send_message(
        chat_id=YOUR_CHAT,
        text=f"🌆 *Evening check-in!*\nDid *{FRIEND_1}* get a lift home?",
        parse_mode="Markdown",
        reply_markup=yn_kb(f"eve_f1_yes_{day}", f"eve_f1_no_{day}")
    )


# ── Extra passenger summary ────────────────────────────────────────────────────
async def send_extra_summary(bot, day: str):
    s = db.day_summary(day)
    if s["extra_passengers"] == 0:
        return
    count = s["extra_passengers"]
    each  = s["ex_owes_each"]
    msg_template = (
        f"Hey! Thanks for the lift today 🚗\n"
        f"Your share of today's costs: {fmt(each)}."
        f"{pay_link(each)}\nThanks! 😊"
    )
    await bot.send_message(
        chat_id=YOUR_CHAT,
        text=(
            f"👤 *Extra passenger charge — {day_label(day)}*\n\n"
            f"{count} extra(s) × {fmt(each)} each = *{fmt(s['ex_owes_total'])}*\n"
            f"_(1 unit share of {fmt(s['parking_cost'])} parking + {fmt(s['petrol'])} petrol "
            f"across {s['pool_units']} main pool units)_\n\n"
            f"💬 Message to send each extra:\n```\n{msg_template}\n```"
        ),
        parse_mode="Markdown"
    )


# ── Late nudge ─────────────────────────────────────────────────────────────────
async def job_late_nudge(context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    if db.is_evening_logged(today) or db.is_skipped(today):
        return
    await context.bot.send_message(
        chat_id=YOUR_CHAT,
        text="⏰ *Reminder* — evening not logged yet!\n\nUse /logpm to log now, or /skip if you didn't drive.",
        parse_mode="Markdown"
    )


# ── Parking flow ───────────────────────────────────────────────────────────────
async def start_parking_flow(bot, user_data, use_current_week=False):
    if use_current_week:
        today  = date.today()
        monday = (today - timedelta(days=today.weekday())).isoformat()
    else:
        monday = last_week_monday()
    days = week_days_for_monday(monday)
    user_data["park_flow"] = {
        "monday":  monday,
        "days":    days,
        "idx":     0,
        "f1_rode": None,
        "f2_rode": None,
        "f3_rode": None,
    }
    await _park_ask_f1(bot, user_data)


async def _park_ask_f1(bot, user_data):
    flow = user_data["park_flow"]
    idx  = flow["idx"]
    if idx >= 7:
        await _handle_parking_done(bot, user_data)
        return
    day = flow["days"][idx]
    if db.is_skipped(day):
        user_data["park_flow"]["idx"] = idx + 1
        await _park_ask_f1(bot, user_data)
        return
    if db.has_any_data(day):
        await _park_ask_type(bot, user_data)
        return
    dname = f"{DAY_NAMES[idx]} {date.fromisoformat(day).strftime('%-d %b')}"
    await bot.send_message(
        chat_id=YOUR_CHAT,
        text=f"📅 *{dname}* — Did *{FRIEND_1}* get a lift?",
        parse_mode="Markdown",
        reply_markup=yn_kb(f"pk_f1_yes_{idx}", f"pk_f1_no_{idx}")
    )

async def _park_ask_f2(bot, user_data):
    idx   = user_data["park_flow"]["idx"]
    day   = user_data["park_flow"]["days"][idx]
    dname = f"{DAY_NAMES[idx]} {date.fromisoformat(day).strftime('%-d %b')}"
    await bot.send_message(
        chat_id=YOUR_CHAT,
        text=f"📅 *{dname}* — Did *{FRIEND_2}* get a lift?",
        parse_mode="Markdown",
        reply_markup=yn_kb(f"pk_f2_yes_{idx}", f"pk_f2_no_{idx}")
    )

async def _park_ask_f3(bot, user_data):
    idx   = user_data["park_flow"]["idx"]
    day   = user_data["park_flow"]["days"][idx]
    dname = f"{DAY_NAMES[idx]} {date.fromisoformat(day).strftime('%-d %b')}"
    await bot.send_message(
        chat_id=YOUR_CHAT,
        text=f"📅 *{dname}* — Did *{FRIEND_3}* get a lift?",
        parse_mode="Markdown",
        reply_markup=yn_kb(f"pk_f3_yes_{idx}", f"pk_f3_no_{idx}")
    )

async def _park_ask_drove(bot, user_data):
    idx   = user_data["park_flow"]["idx"]
    day   = user_data["park_flow"]["days"][idx]
    dname = f"{DAY_NAMES[idx]} {date.fromisoformat(day).strftime('%-d %b')}"
    await bot.send_message(
        chat_id=YOUR_CHAT,
        text=f"📅 *{dname}* — Nobody got a lift. Did you drive at all?",
        parse_mode="Markdown",
        reply_markup=yn_kb(f"pk_drove_yes_{idx}", f"pk_drove_no_{idx}")
    )

async def _park_ask_type(bot, user_data):
    flow      = user_data["park_flow"]
    idx       = flow["idx"]
    day       = flow["days"][idx]
    dname     = f"{DAY_NAMES[idx]} {date.fromisoformat(day).strftime('%-d %b')}"
    s         = db.day_summary(day)
    trip_note = (f" ({FRIEND_1}: {s['friend1_trips']}t, {FRIEND_2}: {s['friend2_trips']}t, "
                 f"{FRIEND_3}: {s['friend3_trips']}t)") if db.has_any_data(day) else ""
    if date.fromisoformat(day).weekday() >= 5:
        await bot.send_message(
            chat_id=YOUR_CHAT,
            text=f"🅿️ *{dname}*{trip_note} — Did you park? (weekend rate £{db.EVENING_RATE})",
            parse_mode="Markdown",
            reply_markup=yn_kb(f"pk_park_yes_{idx}", f"pk_park_no_{idx}")
        )
    else:
        await bot.send_message(
            chat_id=YOUR_CHAT,
            text=f"🅿️ *{dname}*{trip_note} — Did you park?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"☀️ Daytime £{db.WEEKDAY_RATE}", callback_data=f"pk_wd_{idx}"),
                InlineKeyboardButton(f"🌙 Evening £{db.EVENING_RATE}",  callback_data=f"pk_ev_{idx}"),
                InlineKeyboardButton("❌ No parking",                    callback_data=f"pk_park_no_{idx}"),
            ]])
        )

async def _park_next_day(bot, user_data):
    user_data["park_flow"]["idx"]    += 1
    user_data["park_flow"]["f1_rode"] = None
    user_data["park_flow"]["f2_rode"] = None
    user_data["park_flow"]["f3_rode"] = None
    await _park_ask_f1(bot, user_data)

async def _handle_parking_done(bot, user_data):
    monday = user_data["park_flow"]["monday"]
    await _send_weekly_summary(bot, monday)


# ── Weekly summary ─────────────────────────────────────────────────────────────
async def _send_weekly_summary(bot, monday: str):
    days = week_days_for_monday(monday)
    tots = db.weekly_totals(days)

    lines = ["📊 *Weekly Summary*\n"]
    for day in days:
        if db.is_skipped(day):
            continue
        s = db.day_summary(day)
        if s["parking_cost"] == 0 and s["friend1_trips"] == 0 and s["friend2_trips"] == 0 and s["friend3_trips"] == 0:
            continue
        park_str = f"park {fmt(s['parking_cost'])} ({s['parking_type']})" if s["parking_cost"] else "no parking"
        ext_str  = f" + {s['extra_passengers']} extra(s) @{fmt(s['ex_owes_each'])}" if s["extra_passengers"] else ""
        lines.append(
            f"*{day_label(day)}*: petrol {fmt(s['petrol'])} + {park_str}\n"
            f"  {FRIEND_1}: {s['friend1_trips']}t  {FRIEND_2}: {s['friend2_trips']}t  "
            f"{FRIEND_3}: {s['friend3_trips']}t{ext_str}"
        )

    def cap_note(raw, capped):
        return f" _(cap saved {fmt(raw - capped)})_" if raw > capped else ""

    lines.append(
        f"\n*{FRIEND_1}* owes: *{fmt(tots['friend1'])}*\n"
        f"  ↳ petrol {fmt(tots['f1_pet'])} + parking {fmt(tots['f1_park_capped'])}"
        f"{cap_note(tots['f1_park_raw'], tots['f1_park_capped'])}\n"
        f"*{FRIEND_2}* owes: *{fmt(tots['friend2'])}*\n"
        f"  ↳ petrol {fmt(tots['f2_pet'])} + parking {fmt(tots['f2_park_capped'])}"
        f"{cap_note(tots['f2_park_raw'], tots['f2_park_capped'])}\n"
        f"*{FRIEND_3}* owes: *{fmt(tots['friend3'])}*\n"
        f"  ↳ petrol {fmt(tots['f3_pet'])} + parking {fmt(tots['f3_park_capped'])}"
        f"{cap_note(tots['f3_park_raw'], tots['f3_park_capped'])}"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📨 {FRIEND_1}'s message", callback_data=f"send_f1_{monday}")],
        [InlineKeyboardButton(f"📨 {FRIEND_2}'s message", callback_data=f"send_f2_{monday}")],
        [InlineKeyboardButton(f"📨 {FRIEND_3}'s message", callback_data=f"send_f3_{monday}")],
    ])
    await bot.send_message(
        chat_id=YOUR_CHAT, text="\n".join(lines),
        parse_mode="Markdown", reply_markup=kb
    )


# ── Scheduled jobs ─────────────────────────────────────────────────────────────
async def job_morning(context: ContextTypes.DEFAULT_TYPE):
    await start_morning(context.bot, date.today().isoformat())

async def job_evening(context: ContextTypes.DEFAULT_TYPE):
    await start_evening(context.bot, date.today().isoformat())

async def job_weekly(context: ContextTypes.DEFAULT_TYPE):
    await start_parking_flow(context.bot, context.bot_data, use_current_week=True)


# ── Callback handler ───────────────────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    await q.answer()
    d   = q.data
    bot = context.bot
    ud  = context.user_data

    # ── Daily morning flow ──
    if d.startswith("morn_f1_"):
        day = d.replace("morn_f1_yes_","").replace("morn_f1_no_","")
        val = "yes" in d
        db.set_trip(day, "friend1_morning", val)
        await q.edit_message_text(f"*{FRIEND_1}* morning: {'✅' if val else '❌'}", parse_mode="Markdown")
        await bot.send_message(chat_id=YOUR_CHAT,
            text=f"Did *{FRIEND_2}* get a lift in?", parse_mode="Markdown",
            reply_markup=yn_kb(f"morn_f2_yes_{day}", f"morn_f2_no_{day}"))

    elif d.startswith("morn_f2_"):
        day = d.replace("morn_f2_yes_","").replace("morn_f2_no_","")
        val = "yes" in d
        db.set_trip(day, "friend2_morning", val)
        await q.edit_message_text(f"*{FRIEND_2}* morning: {'✅' if val else '❌'}", parse_mode="Markdown")
        await bot.send_message(chat_id=YOUR_CHAT,
            text=f"Did *{FRIEND_3}* get a lift in?", parse_mode="Markdown",
            reply_markup=yn_kb(f"morn_f3_yes_{day}", f"morn_f3_no_{day}"))

    elif d.startswith("morn_f3_"):
        day = d.replace("morn_f3_yes_","").replace("morn_f3_no_","")
        val = "yes" in d
        db.set_trip(day, "friend3_morning", val)
        await q.edit_message_text(
            f"*{FRIEND_3}* morning: {'✅' if val else '❌'}\n✅ Morning logged!", parse_mode="Markdown")
        if ud.get("editing_day") == day:
            await start_evening(bot, day)

    # ── Daily evening flow ──
    elif d.startswith("eve_f1_"):
        day = d.replace("eve_f1_yes_","").replace("eve_f1_no_","")
        val = "yes" in d
        db.set_trip(day, "friend1_evening", val)
        await q.edit_message_text(f"*{FRIEND_1}* evening: {'✅' if val else '❌'}", parse_mode="Markdown")
        await bot.send_message(chat_id=YOUR_CHAT,
            text=f"Did *{FRIEND_2}* get a lift home?", parse_mode="Markdown",
            reply_markup=yn_kb(f"eve_f2_yes_{day}", f"eve_f2_no_{day}"))

    elif d.startswith("eve_f2_"):
        day = d.replace("eve_f2_yes_","").replace("eve_f2_no_","")
        val = "yes" in d
        db.set_trip(day, "friend2_evening", val)
        await q.edit_message_text(f"*{FRIEND_2}* evening: {'✅' if val else '❌'}", parse_mode="Markdown")
        await bot.send_message(chat_id=YOUR_CHAT,
            text=f"Did *{FRIEND_3}* get a lift home?", parse_mode="Markdown",
            reply_markup=yn_kb(f"eve_f3_yes_{day}", f"eve_f3_no_{day}"))

    elif d.startswith("eve_f3_"):
        day = d.replace("eve_f3_yes_","").replace("eve_f3_no_","")
        val = "yes" in d
        db.set_trip(day, "friend3_evening", val)
        ud.pop("editing_day", None)
        db.set_evening_logged(day)
        await q.edit_message_text(
            f"*{FRIEND_3}* evening: {'✅' if val else '❌'}\n✅ Evening logged!", parse_mode="Markdown")
        s = db.day_summary(day)
        await bot.send_message(chat_id=YOUR_CHAT,
            text=(f"📋 *{day_label(day)}*: petrol {fmt(s['petrol'])} + parking logged Sat\n"
                  f"🚗 {FRIEND_1}: {s['friend1_trips']}t  {FRIEND_2}: {s['friend2_trips']}t  "
                  f"{FRIEND_3}: {s['friend3_trips']}t"),
            parse_mode="Markdown")
        await send_extra_summary(bot, day)

    # ── Parking flow ──
    elif d.startswith("pk_f1_"):
        idx = int(d.replace("pk_f1_yes_","").replace("pk_f1_no_",""))
        val = "yes" in d
        ud["park_flow"]["f1_rode"] = val
        day = ud["park_flow"]["days"][idx]
        if val:
            db.set_trip(day, "friend1_morning", 1)
            db.set_trip(day, "friend1_evening", 1)
        await q.edit_message_text(f"*{FRIEND_1}*: {'✅' if val else '❌'}", parse_mode="Markdown")
        await _park_ask_f2(bot, ud)

    elif d.startswith("pk_f2_"):
        idx = int(d.replace("pk_f2_yes_","").replace("pk_f2_no_",""))
        val = "yes" in d
        ud["park_flow"]["f2_rode"] = val
        day = ud["park_flow"]["days"][idx]
        if val:
            db.set_trip(day, "friend2_morning", 1)
            db.set_trip(day, "friend2_evening", 1)
        await q.edit_message_text(f"*{FRIEND_2}*: {'✅' if val else '❌'}", parse_mode="Markdown")
        await _park_ask_f3(bot, ud)

    elif d.startswith("pk_f3_"):
        idx = int(d.replace("pk_f3_yes_","").replace("pk_f3_no_",""))
        val = "yes" in d
        ud["park_flow"]["f3_rode"] = val
        day = ud["park_flow"]["days"][idx]
        if val:
            db.set_trip(day, "friend3_morning", 1)
            db.set_trip(day, "friend3_evening", 1)
        await q.edit_message_text(f"*{FRIEND_3}*: {'✅' if val else '❌'}", parse_mode="Markdown")
        if not ud["park_flow"]["f1_rode"] and not ud["park_flow"]["f2_rode"] and not val:
            await _park_ask_drove(bot, ud)
        else:
            await _park_ask_type(bot, ud)

    elif d.startswith("pk_drove_yes_"):
        await q.edit_message_text("✅ You drove.", parse_mode="Markdown")
        await _park_ask_type(bot, ud)

    elif d.startswith("pk_drove_no_"):
        idx = int(d.replace("pk_drove_no_",""))
        day = ud["park_flow"]["days"][idx]
        db.set_skipped(day, True)
        await q.edit_message_text(f"❌ {DAY_NAMES[idx]} — no drive.", parse_mode="Markdown")
        await _park_next_day(bot, ud)

    elif d.startswith("pk_wd_"):
        idx = int(d.replace("pk_wd_",""))
        day = ud["park_flow"]["days"][idx]
        db.set_parking_type(day, "weekday")
        await q.edit_message_text(f"🅿️ {DAY_NAMES[idx]} — daytime (£{db.WEEKDAY_RATE})", parse_mode="Markdown")
        await _park_next_day(bot, ud)

    elif d.startswith("pk_ev_"):
        idx = int(d.replace("pk_ev_",""))
        day = ud["park_flow"]["days"][idx]
        db.set_parking_type(day, "evening")
        await q.edit_message_text(f"🅿️ {DAY_NAMES[idx]} — evening (£{db.EVENING_RATE})", parse_mode="Markdown")
        await _park_next_day(bot, ud)

    elif d.startswith("pk_park_yes_"):
        idx = int(d.replace("pk_park_yes_",""))
        day = ud["park_flow"]["days"][idx]
        db.set_parking_type(day, "evening")
        await q.edit_message_text(f"🅿️ {DAY_NAMES[idx]} — parked (£{db.EVENING_RATE})", parse_mode="Markdown")
        await _park_next_day(bot, ud)

    elif d.startswith("pk_park_no_"):
        idx = int(d.replace("pk_park_no_",""))
        day = ud["park_flow"]["days"][idx]
        db.set_parking_type(day, "none")
        await q.edit_message_text(f"❌ {DAY_NAMES[idx]} — no parking.", parse_mode="Markdown")
        await _park_next_day(bot, ud)

    # ── Payment messages ──
    elif d.startswith("edit_day_"):
        day = d.replace("edit_day_", "")
        for f in ["friend1_morning","friend1_evening","friend2_morning","friend2_evening",
                  "friend3_morning","friend3_evening"]:
            db.set_trip(day, f, False)
        db.set_extra_passengers(day, 0)
        db.set_skipped(day, False)
        ud["editing_day"] = day
        await q.edit_message_text(f"🔄 *Resetting {day_label(day)} — starting over.*", parse_mode="Markdown")
        await start_morning(bot, day)

    elif d.startswith("send_f1_") or d.startswith("send_f2_") or d.startswith("send_f3_"):
        if d.startswith("send_f1_"):
            monday = d.replace("send_f1_",""); key = "friend1"; name = FRIEND_1
        elif d.startswith("send_f2_"):
            monday = d.replace("send_f2_",""); key = "friend2"; name = FRIEND_2
        else:
            monday = d.replace("send_f3_",""); key = "friend3"; name = FRIEND_3
        tots   = db.weekly_totals(week_days_for_monday(monday))
        amount = tots[key]
        msg    = (f"Hey {name}! 🚗\n\nThis week's lift costs — you owe {fmt(amount)}."
                  f"{pay_link(amount)}\n\nThanks! 😊")
        await q.edit_message_text(
            f"Copy & send to *{name}*:\n\n```\n{msg}\n```", parse_mode="Markdown")


# ── Text input ─────────────────────────────────────────────────────────────────
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    if "awaiting_extra_day" in ud:
        try:
            count = int(update.message.text.strip())
            if count < 1: raise ValueError
            day = ud.pop("awaiting_extra_day")
            db.set_extra_passengers(day, count)
            await update.message.reply_text(
                f"✅ *{count} extra passenger(s) logged for {day_label(day)}*", parse_mode="Markdown")
            await send_extra_summary(context.bot, day)
        except ValueError:
            await update.message.reply_text("Type a whole number e.g. `2`", parse_mode="Markdown")


# ── Commands ───────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🚗 *Car Cost Bot running!*\n\nChat ID: `{update.effective_chat.id}`\n\nType /cmds for all commands.",
        parse_mode="Markdown")

async def cmd_cmds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Commands*\n\n"
        "*Daily*\n"
        "/log — morning check-in\n"
        "/logpm — evening check-in\n"
        "/extra — log extra passenger(s) today\n"
        "/skip — mark today as no-drive\n"
        "/edit — redo a day's check-ins\n\n"
        "*Weekly*\n"
        "/parking — run parking questions\n"
        "/sofar — running totals this week\n"
        "/summary — weekly summary + payment messages\n"
        "/history — last week's summary\n\n"
        "*Info*\n"
        "/rates — show current rates\n"
        "/cmds — this list",
        parse_mode="Markdown")

async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    db.ensure_day(today)
    await start_morning(context.bot, today)

async def cmd_logpm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    db.ensure_day(today)
    await start_evening(context.bot, today)

async def cmd_extra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    db.ensure_day(today)
    context.user_data["awaiting_extra_day"] = today
    await update.message.reply_text(
        f"👤 *Extra passengers today* ({day_label(today)})\n\nHow many extra people got a lift?",
        parse_mode="Markdown")

async def cmd_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    db.set_skipped(today, True)
    await update.message.reply_text(
        f"✅ *{day_label(today)} — no drive.* Skipped.", parse_mode="Markdown")

async def cmd_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    mon   = today - timedelta(days=today.weekday())
    days  = [(mon + timedelta(days=i)).isoformat() for i in range(7)]
    buttons = []
    for day_str in days:
        d = date.fromisoformat(day_str)
        if d > today:
            break
        buttons.append([InlineKeyboardButton(d.strftime("%a %-d %b"), callback_data=f"edit_day_{day_str}")])
    await update.message.reply_text(
        "✏️ *Which day do you want to edit?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons))

async def cmd_parking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    use_current = today.weekday() >= 5
    await start_parking_flow(context.bot, context.user_data, use_current_week=use_current)

async def cmd_sofar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = current_week_days()
    tots = db.weekly_totals(days)
    lines = ["📊 *This week so far*\n"]
    for day_str in days:
        if db.is_skipped(day_str): continue
        s = db.day_summary(day_str)
        if s["parking_cost"] == 0 and s["friend1_trips"] == 0 and s["friend2_trips"] == 0 and s["friend3_trips"] == 0:
            continue
        park_str = f"park {fmt(s['parking_cost'])} ({s['parking_type']})" if s["parking_cost"] else "parking TBC"
        ext_str  = f" + {s['extra_passengers']} extra(s) @{fmt(s['ex_owes_each'])}" if s["extra_passengers"] else ""
        lines.append(
            f"*{day_label(day_str)}*: petrol {fmt(s['petrol'])} + {park_str}\n"
            f"  {FRIEND_1}: {s['friend1_trips']}t  {FRIEND_2}: {s['friend2_trips']}t  "
            f"{FRIEND_3}: {s['friend3_trips']}t{ext_str}")
    if len(lines) == 1:
        lines.append("_Nothing logged yet_")

    def cn(raw, capped):
        return f" (cap saved {fmt(raw-capped)})" if raw > capped else ""

    lines.append(
        f"\n*{FRIEND_1}*: {fmt(tots['friend1'])} (pet {fmt(tots['f1_pet'])} + park {fmt(tots['f1_park_capped'])}"
        f"{cn(tots['f1_park_raw'], tots['f1_park_capped'])})\n"
        f"*{FRIEND_2}*: {fmt(tots['friend2'])} (pet {fmt(tots['f2_pet'])} + park {fmt(tots['f2_park_capped'])}"
        f"{cn(tots['f2_park_raw'], tots['f2_park_capped'])})\n"
        f"*{FRIEND_3}*: {fmt(tots['friend3'])} (pet {fmt(tots['f3_pet'])} + park {fmt(tots['f3_park_capped'])}"
        f"{cn(tots['f3_park_raw'], tots['f3_park_capped'])})"
    )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    monday = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    await _send_weekly_summary(context.bot, monday)

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_weekly_summary(context.bot, last_week_monday())

async def cmd_rates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📌 *Current rates*\n\n"
        f"⛽ Petrol: {fmt(db.PETROL_COST)}/day\n"
        f"☀️ Weekday parking: {fmt(db.WEEKDAY_RATE)}/day\n"
        f"🌙 Evening/weekend: {fmt(db.EVENING_RATE)}/day\n"
        f"🔒 Weekly parking cap: {fmt(db.WEEKLY_CAP)} _(all friends, auto)_\n"
        f"👤 Extra passenger: 1 unit share of daily cost _(doesn't affect named friends)_",
        parse_mode="Markdown")


# ── Scheduler ──────────────────────────────────────────────────────────────────
def setup_jobs(app: Application):
    jq = app.job_queue
    jq.run_daily(job_morning,    time=time(14, 0, tzinfo=TZ), days=WEEKDAYS)
    jq.run_daily(job_evening,    time=time(21, 0, tzinfo=TZ), days=WEEKDAYS)
    jq.run_daily(job_late_nudge, time=time(22, 0, tzinfo=TZ), days=WEEKDAYS)
    jq.run_daily(job_weekly,     time=time(9,  0, tzinfo=TZ), days=(5,))
    logger.info("Jobs scheduled")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    db.init()
    webhook_url = os.environ.get("WEBHOOK_URL", "").rstrip("/")
    port        = int(os.environ.get("PORT", 8080))

    app = Application.builder().token(TOKEN).build()
    setup_jobs(app)

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("cmds",    cmd_cmds))
    app.add_handler(CommandHandler("log",     cmd_log))
    app.add_handler(CommandHandler("logpm",   cmd_logpm))
    app.add_handler(CommandHandler("extra",   cmd_extra))
    app.add_handler(CommandHandler("skip",    cmd_skip))
    app.add_handler(CommandHandler("edit",    cmd_edit))
    app.add_handler(CommandHandler("parking", cmd_parking))
    app.add_handler(CommandHandler("sofar",   cmd_sofar))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("rates",   cmd_rates))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    if webhook_url:
        logger.info(f"Webhook mode on port {port}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=f"{webhook_url}/webhook",
            url_path="/webhook",
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("Polling mode (dev)")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
