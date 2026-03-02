import os
import logging
from datetime import datetime, date, timedelta
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

# ── Config ────────────────────────────────────────────────────────────────────
TOKEN        = os.environ["TELEGRAM_TOKEN"]
YOUR_CHAT    = int(os.environ["YOUR_CHAT_ID"])
FRIEND_1     = os.environ.get("FRIEND_1_NAME", "Fran")
FRIEND_2     = os.environ.get("FRIEND_2_NAME", "Lauren")
TIMEZONE     = os.environ.get("TIMEZONE", "Europe/London")
PAYMENT_LINK = os.environ.get("PAYMENT_LINK", "")
DEFAULT_COST = 5.42

TZ = pytz.timezone(TIMEZONE)


# ── Keyboards ─────────────────────────────────────────────────────────────────
def yn_kb(yes_cb, no_cb):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data=yes_cb),
        InlineKeyboardButton("❌ No",  callback_data=no_cb),
    ]])

def cost_kb(day):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"✅ Use default (£{DEFAULT_COST})", callback_data=f"cost_default_{day}"),
    ]])


# ── Helpers ───────────────────────────────────────────────────────────────────
def fmt(amount): return f"£{amount:.2f}"

def payment_suffix(amount):
    if PAYMENT_LINK:
        return f"\n💸 Pay here: {PAYMENT_LINK} (send {fmt(amount)})"
    return f"\n💸 Please send me {fmt(amount)}"

def current_week_days():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return [(monday + timedelta(days=i)).isoformat() for i in range(7)]


# ── Morning / Evening starters ────────────────────────────────────────────────
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


# ── Scheduled jobs ────────────────────────────────────────────────────────────
async def job_morning(bot): await start_morning(bot, date.today().isoformat())
async def job_evening(bot): await start_evening(bot, date.today().isoformat())

async def job_weekly(bot):
    days   = current_week_days()
    tots   = db.weekly_totals(days)
    f1, f2 = tots["friend1"], tots["friend2"]
    monday = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📨 {FRIEND_1}'s message", callback_data=f"send_f1_{monday}")],
        [InlineKeyboardButton(f"📨 {FRIEND_2}'s message", callback_data=f"send_f2_{monday}")],
    ])
    await bot.send_message(
        chat_id=YOUR_CHAT,
        text=(f"📊 *Weekly Summary*\n\n"
              f"*{FRIEND_1}* owes: {fmt(f1)}\n"
              f"*{FRIEND_2}* owes: {fmt(f2)}\n\n"
              f"Tap to generate payment messages 👇"),
        parse_mode="Markdown", reply_markup=kb
    )


# ── Day summary helper ────────────────────────────────────────────────────────
async def send_day_summary(bot, day):
    s    = db.day_summary(day)
    tots = db.weekly_totals(current_week_days())
    await bot.send_message(
        chat_id=YOUR_CHAT,
        text=(f"📋 *Day logged!*\n\n"
              f"💰 Cost: {fmt(s['cost'])}\n"
              f"🚗 {FRIEND_1}: {s['friend1_trips']} trip(s) → {fmt(s['friend1_owes'])}\n"
              f"🚗 {FRIEND_2}: {s['friend2_trips']} trip(s) → {fmt(s['friend2_owes'])}\n\n"
              f"_Week running: {FRIEND_1} {fmt(tots['friend1'])} · {FRIEND_2} {fmt(tots['friend2'])}_"),
        parse_mode="Markdown"
    )


# ── Callback handler ──────────────────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data

    # morning F1
    if d.startswith("morn_f1_"):
        day = d.replace("morn_f1_yes_","").replace("morn_f1_no_","")
        val = "yes" in d
        db.set_trip(day, "friend1_morning", val)
        await q.edit_message_text(f"*{FRIEND_1}* morning: {'✅' if val else '❌'}", parse_mode="Markdown")
        await context.bot.send_message(
            chat_id=YOUR_CHAT,
            text=f"Did *{FRIEND_2}* get a lift in this morning?",
            parse_mode="Markdown",
            reply_markup=yn_kb(f"morn_f2_yes_{day}", f"morn_f2_no_{day}")
        )

    # morning F2
    elif d.startswith("morn_f2_"):
        day = d.replace("morn_f2_yes_","").replace("morn_f2_no_","")
        val = "yes" in d
        db.set_trip(day, "friend2_morning", val)
        await q.edit_message_text(
            f"*{FRIEND_2}* morning: {'✅' if val else '❌'}\n\n✅ Morning logged!",
            parse_mode="Markdown"
        )

    # evening F1
    elif d.startswith("eve_f1_"):
        day = d.replace("eve_f1_yes_","").replace("eve_f1_no_","")
        val = "yes" in d
        db.set_trip(day, "friend1_evening", val)
        await q.edit_message_text(f"*{FRIEND_1}* evening: {'✅' if val else '❌'}", parse_mode="Markdown")
        await context.bot.send_message(
            chat_id=YOUR_CHAT,
            text=f"Did *{FRIEND_2}* get a lift home?",
            parse_mode="Markdown",
            reply_markup=yn_kb(f"eve_f2_yes_{day}", f"eve_f2_no_{day}")
        )

    # evening F2 → ask cost
    elif d.startswith("eve_f2_"):
        day = d.replace("eve_f2_yes_","").replace("eve_f2_no_","")
        val = "yes" in d
        db.set_trip(day, "friend2_evening", val)
        await q.edit_message_text(f"*{FRIEND_2}* evening: {'✅' if val else '❌'}", parse_mode="Markdown")
        context.user_data["awaiting_cost_day"] = day
        await context.bot.send_message(
            chat_id=YOUR_CHAT,
            text=(f"💰 *Today's cost (parking + fuel)*\n\n"
                  f"Type a number e.g. `6.20`, or tap to use the default:"),
            parse_mode="Markdown",
            reply_markup=cost_kb(day)
        )

    # default cost
    elif d.startswith("cost_default_"):
        day = d.replace("cost_default_","")
        context.user_data.pop("awaiting_cost_day", None)
        db.set_cost(day, DEFAULT_COST)
        await q.edit_message_text(f"✅ Cost set to {fmt(DEFAULT_COST)}", parse_mode="Markdown")
        await send_day_summary(context.bot, day)

    # send payment message
    elif d.startswith("send_f1_") or d.startswith("send_f2_"):
        is_f1  = d.startswith("send_f1_")
        monday = d.replace("send_f1_","").replace("send_f2_","")
        days   = [(date.fromisoformat(monday) + timedelta(days=i)).isoformat() for i in range(7)]
        tots   = db.weekly_totals(days)
        name   = FRIEND_1 if is_f1 else FRIEND_2
        amount = tots["friend1"] if is_f1 else tots["friend2"]
        msg    = (f"Hey {name}! 🚗\n\n"
                  f"This week's lift costs — you owe {fmt(amount)}."
                  f"{payment_suffix(amount)}\n\nThanks! 😊")
        await q.edit_message_text(
            f"Copy & send to *{name}*:\n\n```\n{msg}\n```",
            parse_mode="Markdown"
        )


# ── Cost text input ───────────────────────────────────────────────────────────
async def cost_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    day = context.user_data.get("awaiting_cost_day")
    if not day:
        return
    try:
        cost = float(update.message.text.strip().replace("£","").replace(",",""))
        db.set_cost(day, cost)
        context.user_data.pop("awaiting_cost_day")
        await update.message.reply_text(f"✅ Cost set to {fmt(cost)}")
        await send_day_summary(context.bot, day)
    except ValueError:
        await update.message.reply_text("Just type a number, e.g. `4.50` or `0`", parse_mode="Markdown")


# ── Commands ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🚗 *Car Cost Bot is running!*\n\n"
        f"Chat ID: `{update.effective_chat.id}`\n\n"
        f"Auto messages: *2pm* (morning) & *9pm* (evening) Mon–Fri\n"
        f"Weekly summary: *Saturday 9am*\n\n"
        f"/log — log this morning manually\n"
        f"/logpm — log this evening manually\n"
        f"/sofar — running total this week\n"
        f"/summary — trigger weekly payment messages",
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

async def cmd_sofar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = current_week_days()
    tots = db.weekly_totals(days)
    lines = ["📊 *This week so far*\n"]
    for day_str in days:
        s = db.day_summary(day_str)
        if s["cost"] == 0 and s["friend1_trips"] == 0 and s["friend2_trips"] == 0:
            continue
        label = date.fromisoformat(day_str).strftime("%a %-d %b")
        lines.append(
            f"*{label}* — {fmt(s['cost'])}\n"
            f"  {FRIEND_1}: {s['friend1_trips']} trip(s) = {fmt(s['friend1_owes'])}\n"
            f"  {FRIEND_2}: {s['friend2_trips']} trip(s) = {fmt(s['friend2_owes'])}"
        )
    if len(lines) == 1:
        lines.append("_Nothing logged yet this week_")
    lines.append(f"\n*TOTAL → {FRIEND_1}: {fmt(tots['friend1'])} · {FRIEND_2}: {fmt(tots['friend2'])}*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await job_weekly(context.bot)


# ── Scheduler wiring ──────────────────────────────────────────────────────────
async def post_init(app: Application):
    scheduler = AsyncIOScheduler(timezone=TZ)
    scheduler.add_job(lambda: job_morning(app.bot), CronTrigger(day_of_week="mon-fri", hour=14, minute=0, timezone=TZ))
    scheduler.add_job(lambda: job_evening(app.bot), CronTrigger(day_of_week="mon-fri", hour=21, minute=0, timezone=TZ))
    scheduler.add_job(lambda: job_weekly(app.bot),  CronTrigger(day_of_week="sat",     hour=9,  minute=0, timezone=TZ))
    scheduler.start()
    logger.info("Scheduler started")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    db.init()
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("log",     cmd_log))
    app.add_handler(CommandHandler("logpm",   cmd_logpm))
    app.add_handler(CommandHandler("sofar",   cmd_sofar))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cost_input))
    logger.info("Bot running")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
