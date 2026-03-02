import os
import logging
from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CallbackQueryHandler,
    CommandHandler, MessageHandler, filters, ContextTypes,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
TOKEN        = os.environ["TELEGRAM_TOKEN"]
YOUR_CHAT    = int(os.environ["YOUR_CHAT_ID"])
FRIEND_1     = os.environ.get("FRIEND_1_NAME", "Fran")
FRIEND_2     = os.environ.get("FRIEND_2_NAME", "Lauren")
TIMEZONE     = os.environ.get("TIMEZONE", "Europe/London")
PAYMENT_LINK = os.environ.get("PAYMENT_LINK", "")
TZ           = pytz.timezone(TIMEZONE)
DAY_NAMES    = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


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

def week_days_for_monday(monday_str: str):
    mon = date.fromisoformat(monday_str)
    return [(mon + timedelta(days=i)).isoformat() for i in range(7)]


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
        text=f"🌆 *Evening check-in!*\nDid *{FRIEND_1}* get a lift home this evening?",
        parse_mode="Markdown",
        reply_markup=yn_kb(f"eve_f1_yes_{day}", f"eve_f1_no_{day}")
    )


# ── Extra passenger flow ───────────────────────────────────────────────────────
async def send_extra_summary(bot, day: str):
    """After evening log: if extra passengers that day, show what to charge them."""
    s = db.day_summary(day)
    if s["extra_passengers"] == 0:
        return
    day_label = date.fromisoformat(day).strftime("%a %-d %b")
    await bot.send_message(
        chat_id=YOUR_CHAT,
        text=(
            f"👤 *Extra passenger charge — {day_label}*\n\n"
            f"You had *{s['extra_passengers']}* extra passenger(s) today.\n"
            f"Their share: *{fmt(s['extra_owes'])}*\n\n"
            f"_(Parking {fmt(s['ex_park'])} + petrol {fmt(s['ex_pet'])})_\n\n"
            f"💬 Message to send them:\n"
            f"```\nHey! Thanks for the lift today 🚗\n"
            f"Your share of today's costs comes to {fmt(s['extra_owes'])}."
            f"{pay_link(s['extra_owes'])}\nThanks! 😊\n```"
        ),
        parse_mode="Markdown"
    )


# ── Parking weekly flow ────────────────────────────────────────────────────────
async def start_parking_flow(bot, user_data):
    today  = date.today()
    monday = (today - timedelta(days=today.weekday() + 7)).isoformat()
    days   = week_days_for_monday(monday)
    user_data["park_flow"] = {"monday": monday, "days": days, "idx": 0}
    await _ask_next_parking_day(bot, user_data)

async def _ask_next_parking_day(bot, user_data):
    flow = user_data["park_flow"]
    idx  = flow["idx"]
    if idx >= 7:
        await _handle_parking_done(bot, user_data)
        return
    day      = flow["days"][idx]
    day_name = DAY_NAMES[idx]
    await bot.send_message(
        chat_id=YOUR_CHAT,
        text=f"🅿️ Did you *park on {day_name}*? ({date.fromisoformat(day).strftime('%-d %b')})",
        parse_mode="Markdown",
        reply_markup=yn_kb(f"park_yes_{idx}_{day}", f"park_no_{idx}_{day}")
    )

async def _handle_parking_done(bot, user_data):
    """Parking questions complete — check if F2 cap prompt needed, then show summary."""
    monday = user_data["park_flow"]["monday"]
    days   = week_days_for_monday(monday)
    tots   = db.weekly_totals(days)

    if tots["f2_over_cap"]:
        # Ask whether to give F2 the capped fare
        saving = tots["f2_cap_saving"]
        await bot.send_message(
            chat_id=YOUR_CHAT,
            text=(
                f"⚠️ *{FRIEND_2}'s parking this week*\n\n"
                f"Uncapped share: *{fmt(tots['f2_park_raw'])}*\n"
                f"Capped share:   *{fmt(tots['f2_park_capped'])}*\n"
                f"_(saving {fmt(saving)} for {FRIEND_2})_\n\n"
                f"Do you want to give *{FRIEND_2}* the capped fare?"
            ),
            parse_mode="Markdown",
            reply_markup=yn_kb(f"f2cap_yes_{monday}", f"f2cap_no_{monday}")
        )
    else:
        await _send_weekly_summary(bot, monday, use_f2_cap=False)


# ── Weekly summary ─────────────────────────────────────────────────────────────
async def _send_weekly_summary(bot, monday: str, use_f2_cap: bool = False):
    days = week_days_for_monday(monday)
    tots = db.weekly_totals(days)
    f1   = tots["friend1"]
    f2   = tots["friend2_capped"] if use_f2_cap else tots["friend2_raw"]

    lines = ["📊 *Weekly Summary*\n"]
    for day in days:
        s = db.day_summary(day)
        if s["parking_cost"] == 0 and s["friend1_trips"] == 0 and s["friend2_trips"] == 0:
            continue
        label    = date.fromisoformat(day).strftime("%a %-d %b")
        park_str = f"park {fmt(s['parking_cost'])} ({s['parking_type']})" if s["parking_cost"] else "no parking"
        ext_str  = f" + {s['extra_passengers']} extra" if s["extra_passengers"] else ""
        lines.append(
            f"*{label}*: petrol {fmt(s['petrol'])} + {park_str}\n"
            f"  {FRIEND_1}: {s['friend1_trips']} trip(s)  "
            f"{FRIEND_2}: {s['friend2_trips']} trip(s){ext_str}"
        )

    # F1 cap note
    f1_cap_note = ""
    if tots["f1_park_raw"] > tots["f1_park_capped"]:
        f1_cap_note = f" _(cap saved {fmt(tots['f1_park_raw'] - tots['f1_park_capped'])})_"

    # F2 cap note
    f2_park_used = tots["f2_park_capped"] if use_f2_cap else tots["f2_park_raw"]
    f2_cap_note  = " _(capped)_" if use_f2_cap else ""

    lines.append(
        f"\n*{FRIEND_1}* owes: *{fmt(f1)}*\n"
        f"  ↳ petrol {fmt(tots['f1_pet'])} + parking {fmt(tots['f1_park_capped'])}{f1_cap_note}\n"
        f"*{FRIEND_2}* owes: *{fmt(f2)}*\n"
        f"  ↳ petrol {fmt(tots['f2_pet'])} + parking {fmt(f2_park_used)}{f2_cap_note}"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📨 {FRIEND_1}'s message", callback_data=f"send_f1_{monday}_{int(use_f2_cap)}")],
        [InlineKeyboardButton(f"📨 {FRIEND_2}'s message", callback_data=f"send_f2_{monday}_{int(use_f2_cap)}")],
    ])
    await bot.send_message(
        chat_id=YOUR_CHAT,
        text="\n".join(lines),
        parse_mode="Markdown",
        reply_markup=kb
    )


# ── Scheduled jobs ─────────────────────────────────────────────────────────────
async def job_morning(bot): await start_morning(bot, date.today().isoformat())
async def job_evening(bot): await start_evening(bot, date.today().isoformat())
_sched_user_data = {}
async def job_weekly(bot):  await start_parking_flow(bot, _sched_user_data)


# ── Callback handler ───────────────────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q  = update.callback_query
    await q.answer()
    d  = q.data
    bot = context.bot
    ud  = context.user_data

    # Morning F1
    if d.startswith("morn_f1_"):
        day = d.replace("morn_f1_yes_","").replace("morn_f1_no_","")
        val = "yes" in d
        db.set_trip(day, "friend1_morning", val)
        await q.edit_message_text(f"*{FRIEND_1}* morning: {'✅' if val else '❌'}", parse_mode="Markdown")
        await bot.send_message(
            chat_id=YOUR_CHAT,
            text=f"Did *{FRIEND_2}* get a lift in this morning?",
            parse_mode="Markdown",
            reply_markup=yn_kb(f"morn_f2_yes_{day}", f"morn_f2_no_{day}")
        )

    # Morning F2
    elif d.startswith("morn_f2_"):
        day = d.replace("morn_f2_yes_","").replace("morn_f2_no_","")
        val = "yes" in d
        db.set_trip(day, "friend2_morning", val)
        await q.edit_message_text(
            f"*{FRIEND_2}* morning: {'✅' if val else '❌'}\n✅ Morning logged!",
            parse_mode="Markdown"
        )

    # Evening F1
    elif d.startswith("eve_f1_"):
        day = d.replace("eve_f1_yes_","").replace("eve_f1_no_","")
        val = "yes" in d
        db.set_trip(day, "friend1_evening", val)
        await q.edit_message_text(f"*{FRIEND_1}* evening: {'✅' if val else '❌'}", parse_mode="Markdown")
        await bot.send_message(
            chat_id=YOUR_CHAT,
            text=f"Did *{FRIEND_2}* get a lift home?",
            parse_mode="Markdown",
            reply_markup=yn_kb(f"eve_f2_yes_{day}", f"eve_f2_no_{day}")
        )

    # Evening F2 → done → show extra passenger summary if any
    elif d.startswith("eve_f2_"):
        day = d.replace("eve_f2_yes_","").replace("eve_f2_no_","")
        val = "yes" in d
        db.set_trip(day, "friend2_evening", val)
        await q.edit_message_text(
            f"*{FRIEND_2}* evening: {'✅' if val else '❌'}\n✅ Evening logged!",
            parse_mode="Markdown"
        )
        # send day snapshot
        s = db.day_summary(day)
        await bot.send_message(
            chat_id=YOUR_CHAT,
            text=(
                f"📋 *Today*: petrol {fmt(s['petrol'])} + parking logged Sat\n"
                f"🚗 {FRIEND_1}: {s['friend1_trips']} trip(s)  "
                f"{FRIEND_2}: {s['friend2_trips']} trip(s)"
            ),
            parse_mode="Markdown"
        )
        # extra passenger charge if any
        await send_extra_summary(bot, day)

    # Parking: yes → ask type
    elif d.startswith("park_yes_"):
        parts    = d.split("_")
        idx      = int(parts[2])
        day      = "_".join(parts[3:])
        weekday_num = date.fromisoformat(day).weekday()
        if weekday_num <= 4:
            await q.edit_message_text(
                f"✅ Parked on {DAY_NAMES[idx]}. Daytime (8am–5pm £3.50) or evening only (5pm–8am £2.50)?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("☀️ Daytime £3.50", callback_data=f"park_wd_{idx}_{day}"),
                    InlineKeyboardButton("🌙 Evening £2.50", callback_data=f"park_ev_{idx}_{day}"),
                ]])
            )
        else:
            db.set_parking_type(day, "evening")
            await q.edit_message_text(f"✅ {DAY_NAMES[idx]} — weekend rate (£2.50)", parse_mode="Markdown")
            ud["park_flow"]["idx"] = idx + 1
            await _ask_next_parking_day(bot, ud)

    # Parking: no
    elif d.startswith("park_no_"):
        parts = d.split("_")
        idx   = int(parts[2])
        day   = "_".join(parts[3:])
        db.set_parking_type(day, "none")
        await q.edit_message_text(f"❌ No parking on {DAY_NAMES[idx]}.", parse_mode="Markdown")
        ud["park_flow"]["idx"] = idx + 1
        await _ask_next_parking_day(bot, ud)

    # Parking type: weekday
    elif d.startswith("park_wd_"):
        parts = d.split("_")
        idx   = int(parts[2])
        day   = "_".join(parts[3:])
        db.set_parking_type(day, "weekday")
        await q.edit_message_text(f"✅ {DAY_NAMES[idx]} — daytime (£3.50)", parse_mode="Markdown")
        ud["park_flow"]["idx"] = idx + 1
        await _ask_next_parking_day(bot, ud)

    # Parking type: evening
    elif d.startswith("park_ev_"):
        parts = d.split("_")
        idx   = int(parts[2])
        day   = "_".join(parts[3:])
        db.set_parking_type(day, "evening")
        await q.edit_message_text(f"✅ {DAY_NAMES[idx]} — evening (£2.50)", parse_mode="Markdown")
        ud["park_flow"]["idx"] = idx + 1
        await _ask_next_parking_day(bot, ud)

    # F2 cap prompt: yes
    elif d.startswith("f2cap_yes_"):
        monday = d.replace("f2cap_yes_","")
        await q.edit_message_text(f"✅ Giving *{FRIEND_2}* the capped fare.", parse_mode="Markdown")
        await _send_weekly_summary(bot, monday, use_f2_cap=True)

    # F2 cap prompt: no
    elif d.startswith("f2cap_no_"):
        monday = d.replace("f2cap_no_","")
        await q.edit_message_text(f"✅ Charging *{FRIEND_2}* full uncapped amount.", parse_mode="Markdown")
        await _send_weekly_summary(bot, monday, use_f2_cap=False)

    # Send payment messages
    elif d.startswith("send_f1_") or d.startswith("send_f2_"):
        is_f1    = d.startswith("send_f1_")
        rest     = d.replace("send_f1_","").replace("send_f2_","")
        *mon_parts, cap_flag = rest.split("_")
        monday   = "_".join(mon_parts)
        use_cap  = cap_flag == "1"
        days     = week_days_for_monday(monday)
        tots     = db.weekly_totals(days)
        name     = FRIEND_1 if is_f1 else FRIEND_2
        if is_f1:
            amount = tots["friend1"]
        else:
            amount = tots["friend2_capped"] if use_cap else tots["friend2_raw"]
        msg = (f"Hey {name}! 🚗\n\nThis week's lift costs — you owe {fmt(amount)}."
               f"{pay_link(amount)}\n\nThanks! 😊")
        await q.edit_message_text(
            f"Copy & send to *{name}*:\n\n```\n{msg}\n```",
            parse_mode="Markdown"
        )


# ── Text input: extra passenger count ─────────────────────────────────────────
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    if "awaiting_extra_day" in ud:
        try:
            count = int(update.message.text.strip())
            if count < 1:
                raise ValueError
            day = ud.pop("awaiting_extra_day")
            db.set_extra_passengers(day, count)
            await update.message.reply_text(
                f"✅ *{count} extra passenger(s) added for {date.fromisoformat(day).strftime('%a %-d %b')}*",
                parse_mode="Markdown"
            )
            await send_extra_summary(context.bot, day)
        except ValueError:
            await update.message.reply_text("Please type a whole number e.g. `1`", parse_mode="Markdown")


# ── Commands ───────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🚗 *Car Cost Bot running!*\n\n"
        f"Chat ID: `{update.effective_chat.id}`\n\n"
        f"Schedule:\n"
        f"  *2pm* Mon–Fri → morning check-in\n"
        f"  *9pm* Mon–Fri → evening check-in\n"
        f"  *Sat 9am* → parking questions → weekly summary\n\n"
        f"Rates per driving day:\n"
        f"  ⛽ Petrol: £{db.PETROL_COST} (never capped)\n"
        f"  ☀️ Parking weekday: £{db.WEEKDAY_RATE} (cap £{db.WEEKLY_CAP}/wk for {FRIEND_1})\n"
        f"  🌙 Parking evening/wknd: £{db.EVENING_RATE} (cap £{db.WEEKLY_CAP}/wk for {FRIEND_1})\n"
        f"  {FRIEND_2}: uncapped (you'll be asked)\n\n"
        f"/log — morning check-in\n"
        f"/logpm — evening check-in\n"
        f"/extra — log extra passenger today\n"
        f"/parking — run parking questions now\n"
        f"/sofar — running week total\n"
        f"/summary — weekly summary",
        parse_mode="Markdown"
    )

async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    db.ensure_day(today)
    await start_morning(context.bot, today)

async def cmd_logpm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    db.ensure_day(today)
    await start_evening(context.bot, today)

async def cmd_extra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log extra passengers for today."""
    today = date.today().isoformat()
    db.ensure_day(today)
    context.user_data["awaiting_extra_day"] = today
    await update.message.reply_text(
        f"👤 *Extra passengers today* ({date.today().strftime('%a %-d %b')})\n\n"
        f"How many extra people got a lift? (type a number)",
        parse_mode="Markdown"
    )

async def cmd_parking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_parking_flow(context.bot, context.user_data)

async def cmd_sofar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = current_week_days()
    tots = db.weekly_totals(days)
    lines = ["📊 *This week so far*\n"]
    for day_str in days:
        s = db.day_summary(day_str)
        if s["parking_cost"] == 0 and s["friend1_trips"] == 0 and s["friend2_trips"] == 0:
            continue
        label    = date.fromisoformat(day_str).strftime("%a %-d %b")
        park_str = f"park {fmt(s['parking_cost'])} ({s['parking_type']})" if s["parking_cost"] else "parking TBC"
        ext_str  = f" + {s['extra_passengers']} extra" if s["extra_passengers"] else ""
        lines.append(
            f"*{label}*: petrol {fmt(s['petrol'])} + {park_str}\n"
            f"  {FRIEND_1}: {s['friend1_trips']} trip(s)  "
            f"{FRIEND_2}: {s['friend2_trips']} trip(s){ext_str}"
        )
    if len(lines) == 1:
        lines.append("_Nothing logged yet_")

    cap_note = ""
    if tots["f1_park_raw"] > tots["f1_park_capped"]:
        cap_note = f" _(cap, saved {fmt(tots['f1_park_raw'] - tots['f1_park_capped'])})_"

    lines.append(
        f"\n*{FRIEND_1}*: {fmt(tots['friend1'])} "
        f"(petrol {fmt(tots['f1_pet'])} + parking {fmt(tots['f1_park_capped'])}{cap_note})\n"
        f"*{FRIEND_2}*: {fmt(tots['friend2_raw'])} "
        f"(petrol {fmt(tots['f2_pet'])} + parking {fmt(tots['f2_park_raw'])})"
    )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today  = date.today()
    monday = (today - timedelta(days=today.weekday())).isoformat()
    await _send_weekly_summary(context.bot, monday, use_f2_cap=False)


# ── Scheduler wiring ───────────────────────────────────────────────────────────
async def post_init(app: Application):
    scheduler = AsyncIOScheduler(timezone=TZ)
    scheduler.add_job(lambda: job_morning(app.bot), CronTrigger(day_of_week="mon-fri", hour=14, minute=0,  timezone=TZ))
    scheduler.add_job(lambda: job_evening(app.bot), CronTrigger(day_of_week="mon-fri", hour=21, minute=0,  timezone=TZ))
    scheduler.add_job(lambda: job_weekly(app.bot),  CronTrigger(day_of_week="sat",     hour=9,  minute=0,  timezone=TZ))
    scheduler.start()
    logger.info("Scheduler started")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    db.init()
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("log",     cmd_log))
    app.add_handler(CommandHandler("logpm",   cmd_logpm))
    app.add_handler(CommandHandler("extra",   cmd_extra))
    app.add_handler(CommandHandler("parking", cmd_parking))
    app.add_handler(CommandHandler("sofar",   cmd_sofar))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    logger.info("Bot running")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
