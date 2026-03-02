import os
import json
import logging
from datetime import datetime, date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
TOKEN      = os.environ["TELEGRAM_TOKEN"]
YOUR_CHAT  = int(os.environ["YOUR_CHAT_ID"])
FRIEND_1   = os.environ.get("FRIEND_1_NAME", "Fran")
FRIEND_2   = os.environ.get("FRIEND_2_NAME", "Lauren")
TIMEZONE   = os.environ.get("TIMEZONE", "Europe/London")
PAYMENT_LINK = os.environ.get("PAYMENT_LINK", "")  # e.g. monzo.me/yourname

TZ = pytz.timezone(TIMEZONE)

# conversation states
ASK_COST = 1


# ── Helpers ──────────────────────────────────────────────────────────────────
def yn_keyboard(callback_yes: str, callback_no: str):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data=callback_yes),
        InlineKeyboardButton("❌ No",  callback_data=callback_no),
    ]])


def fmt_money(amount: float) -> str:
    return f"£{amount:.2f}"


def payment_suffix(name: str, amount: float) -> str:
    if PAYMENT_LINK:
        return f"\n💸 Pay here: {PAYMENT_LINK} (send {fmt_money(amount)})"
    return f"\n💸 Please send me {fmt_money(amount)}"


# ── Scheduled jobs ────────────────────────────────────────────────────────────
async def ask_morning(context: ContextTypes.DEFAULT_TYPE):
    """2 pm: ask about morning lifts"""
    today = date.today().isoformat()
    db.ensure_day(today)
    await context.bot.send_message(
        chat_id=YOUR_CHAT,
        text=f"🚗 *Morning check-in!*\nDid *{FRIEND_1}* get a lift in this morning?",
        parse_mode="Markdown",
        reply_markup=yn_keyboard(f"morn_f1_yes_{today}", f"morn_f1_no_{today}")
    )


async def ask_evening(context: ContextTypes.DEFAULT_TYPE):
    """9 pm: ask about evening lifts"""
    today = date.today().isoformat()
    db.ensure_day(today)
    await context.bot.send_message(
        chat_id=YOUR_CHAT,
        text=f"🌆 *Evening check-in!*\nDid *{FRIEND_1}* get a lift home this evening?",
        parse_mode="Markdown",
        reply_markup=yn_keyboard(f"eve_f1_yes_{today}", f"eve_f1_no_{today}")
    )


async def send_weekly_summary(context: ContextTypes.DEFAULT_TYPE):
    """Saturday 9am: calculate week and show what friends owe"""
    # find Monday–Friday of the just-finished week
    today = date.today()
    monday = today - timedelta(days=today.weekday() + 1)  # last Monday
    days = [(monday + timedelta(days=i)).isoformat() for i in range(5)]

    totals = db.weekly_totals(days)
    f1_owes = totals["friend1"]
    f2_owes = totals["friend2"]

    # summary to you
    summary = (
        f"📊 *Weekly Summary*\n\n"
        f"*{FRIEND_1}* owes you: {fmt_money(f1_owes)}\n"
        f"*{FRIEND_2}* owes you: {fmt_money(f2_owes)}\n\n"
        f"Tap below to send them their payment request 👇"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📨 Send {FRIEND_1}'s message", callback_data=f"send_f1_{monday.isoformat()}")],
        [InlineKeyboardButton(f"📨 Send {FRIEND_2}'s message", callback_data=f"send_f2_{monday.isoformat()}")],
    ])
    await context.bot.send_message(
        chat_id=YOUR_CHAT, text=summary,
        parse_mode="Markdown", reply_markup=keyboard
    )


# ── Callback handlers ─────────────────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # ── Morning friend 1 ──
    if data.startswith("morn_f1_"):
        day = data.split("morn_f1_")[1].replace("yes_", "").replace("no_", "")
        val = "yes" in data
        db.set_trip(day, "friend1_morning", val)
        label = "✅ Yes" if val else "❌ No"
        await query.edit_message_text(f"Got it! *{FRIEND_1}* morning: {label}", parse_mode="Markdown")
        await context.bot.send_message(
            chat_id=YOUR_CHAT,
            text=f"Did *{FRIEND_2}* get a lift in this morning?",
            parse_mode="Markdown",
            reply_markup=yn_keyboard(f"morn_f2_yes_{day}", f"morn_f2_no_{day}")
        )

    # ── Morning friend 2 ──
    elif data.startswith("morn_f2_"):
        day = data.split("morn_f2_")[1].replace("yes_", "").replace("no_", "")
        val = "yes" in data
        db.set_trip(day, "friend2_morning", val)
        label = "✅ Yes" if val else "❌ No"
        await query.edit_message_text(f"Got it! *{FRIEND_2}* morning: {label}\n\n✅ Morning logged!", parse_mode="Markdown")

    # ── Evening friend 1 ──
    elif data.startswith("eve_f1_"):
        day = data.split("eve_f1_")[1].replace("yes_", "").replace("no_", "")
        val = "yes" in data
        db.set_trip(day, "friend1_evening", val)
        label = "✅ Yes" if val else "❌ No"
        await query.edit_message_text(f"Got it! *{FRIEND_1}* evening: {label}", parse_mode="Markdown")
        await context.bot.send_message(
            chat_id=YOUR_CHAT,
            text=f"Did *{FRIEND_2}* get a lift home?",
            parse_mode="Markdown",
            reply_markup=yn_keyboard(f"eve_f2_yes_{day}", f"eve_f2_no_{day}")
        )

    # ── Evening friend 2 → then ask cost ──
    elif data.startswith("eve_f2_"):
        day = data.split("eve_f2_")[1].replace("yes_", "").replace("no_", "")
        val = "yes" in data
        db.set_trip(day, "friend2_evening", val)
        label = "✅ Yes" if val else "❌ No"
        await query.edit_message_text(f"Got it! *{FRIEND_2}* evening: {label}", parse_mode="Markdown")
        context.user_data["awaiting_cost_day"] = day
        await context.bot.send_message(
            chat_id=YOUR_CHAT,
            text="💰 Any parking or fuel costs today?\n_(type a number e.g. `4.50`, or `0` if none)_",
            parse_mode="Markdown"
        )

    # ── Send payment messages ──
    elif data.startswith("send_f1_"):
        monday = data.replace("send_f1_", "")
        days = [(date.fromisoformat(monday) + timedelta(days=i)).isoformat() for i in range(5)]
        totals = db.weekly_totals(days)
        amount = totals["friend1"]
        msg = (
            f"Hey {FRIEND_1}! 🚗\n\n"
            f"This week's lift costs are in — you owe *{fmt_money(amount)}*."
            f"{payment_suffix(FRIEND_1, amount)}\n\nThanks! 😊"
        )
        await query.edit_message_text(f"Here's *{FRIEND_1}'s* message — copy & send it:\n\n```\n{msg}\n```", parse_mode="Markdown")

    elif data.startswith("send_f2_"):
        monday = data.replace("send_f2_", "")
        days = [(date.fromisoformat(monday) + timedelta(days=i)).isoformat() for i in range(5)]
        totals = db.weekly_totals(days)
        amount = totals["friend2"]
        msg = (
            f"Hey {FRIEND_2}! 🚗\n\n"
            f"This week's lift costs are in — you owe *{fmt_money(amount)}*."
            f"{payment_suffix(FRIEND_2, amount)}\n\nThanks! 😊"
        )
        await query.edit_message_text(f"Here's *{FRIEND_2}'s* message — copy & send it:\n\n```\n{msg}\n```", parse_mode="Markdown")


# ── Cost input handler ────────────────────────────────────────────────────────
async def cost_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    day = context.user_data.get("awaiting_cost_day")
    if not day:
        return
    try:
        cost = float(update.message.text.strip().replace("£", "").replace(",", ""))
        db.set_cost(day, cost)
        context.user_data.pop("awaiting_cost_day")

        # show mini daily summary
        summary = db.day_summary(day)
        await update.message.reply_text(
            f"✅ *Day logged!*\n\n"
            f"💰 Cost: {fmt_money(cost)}\n"
            f"🚗 {FRIEND_1}: {summary['friend1_trips']} trip(s)\n"
            f"🚗 {FRIEND_2}: {summary['friend2_trips']} trip(s)\n"
            f"📊 {FRIEND_1} owes: {fmt_money(summary['friend1_owes'])}\n"
            f"📊 {FRIEND_2} owes: {fmt_money(summary['friend2_owes'])}",
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("Please type just a number, e.g. `4.50` or `0`", parse_mode="Markdown")


# ── Manual commands ───────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"🚗 *Car Cost Bot is running!*\n\n"
        f"Your chat ID is: `{chat_id}`\n\n"
        f"I'll message you at *2pm* and *9pm* on weekdays.\n\n"
        f"Commands:\n"
        f"/log — manually log today\n"
        f"/week — see this week's running total\n"
        f"/summary — trigger the weekly payment messages",
        parse_mode="Markdown"
    )


async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger today's morning questions"""
    today = date.today().isoformat()
    db.ensure_day(today)
    await update.message.reply_text(
        f"🚗 Did *{FRIEND_1}* get a lift in this morning?",
        parse_mode="Markdown",
        reply_markup=yn_keyboard(f"morn_f1_yes_{today}", f"morn_f1_no_{today}")
    )


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show running weekly total"""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    days = [(monday + timedelta(days=i)).isoformat() for i in range(5)]
    totals = db.weekly_totals(days)
    await update.message.reply_text(
        f"📊 *This week so far:*\n\n"
        f"*{FRIEND_1}* owes: {fmt_money(totals['friend1'])}\n"
        f"*{FRIEND_2}* owes: {fmt_money(totals['friend2'])}",
        parse_mode="Markdown"
    )


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger weekly summary"""
    await send_weekly_summary(context)


# ── Main ──────────────────────────────────────────────────────────────────────
async def post_init(app: Application):
    """Wire up scheduler after bot is initialised."""
    scheduler = AsyncIOScheduler(timezone=TZ)

    async def _ask_morning():
        class Ctx:
            bot = app.bot
            user_data = {}
        await ask_morning(Ctx())

    async def _ask_evening():
        class Ctx:
            bot = app.bot
            user_data = {}
        await ask_evening(Ctx())

    async def _weekly():
        class Ctx:
            bot = app.bot
            user_data = {}
        await send_weekly_summary(Ctx())

    scheduler.add_job(_ask_morning, CronTrigger(day_of_week="mon-fri", hour=14, minute=0,  timezone=TZ))
    scheduler.add_job(_ask_evening, CronTrigger(day_of_week="mon-fri", hour=21, minute=0,  timezone=TZ))
    scheduler.add_job(_weekly,      CronTrigger(day_of_week="sat",     hour=9,  minute=0,  timezone=TZ))
    scheduler.start()
    logger.info("Scheduler started")


def main():
    db.init()

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("log",     cmd_log))
    app.add_handler(CommandHandler("week",    cmd_week))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cost_input))

    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
