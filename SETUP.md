# 🚗 Car Cost Bot — Setup Guide

## What this does
A Telegram bot that messages you at 2pm and 9pm on weekdays, asks who got a lift,
asks for the day's costs, and on Saturday gives you ready-to-send payment messages
for Fran and Lauren — with your Monzo/Revolut link included.

---

## Step 1 — Create your Telegram bot (2 minutes)

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Give it a name (e.g. "Car Cost Bot") and a username (e.g. `mycarbot_bot`)
4. BotFather gives you a **token** — copy it. Looks like: `7123456789:AAFxxx...`

---

## Step 2 — Get your Chat ID

1. Search for **@userinfobot** on Telegram
2. Send it any message
3. It replies with your **Chat ID** — copy it. Looks like: `123456789`

---

## Step 3 — Deploy to Railway (free, always-on)

1. Go to [railway.app](https://railway.app) and sign up (free)
2. Click **"New Project" → "Deploy from GitHub"**
   - First push this folder to a GitHub repo (or use "Empty Project" and upload files)
3. Add these **environment variables** in Railway's settings:

```
TELEGRAM_TOKEN    = (your token from Step 1)
YOUR_CHAT_ID      = (your chat ID from Step 2)
FRIEND_1_NAME     = Fran
FRIEND_2_NAME     = Lauren
TIMEZONE          = Europe/London
PAYMENT_LINK      = monzo.me/yourname   ← optional
```

4. Railway auto-deploys. Bot is live!

---

## Step 4 — Test it

1. Open Telegram, find your bot, send `/start`
2. It shows your chat ID (confirm it matches) and confirms it's running
3. Send `/log` to manually trigger today's questions right now

---

## Commands

| Command | What it does |
|---------|-------------|
| `/start` | Confirms bot is running |
| `/log` | Manually start today's questions now |
| `/week` | See the running total for this week |
| `/summary` | Manually trigger the weekly payment messages |

---

## Daily flow

**2:00pm Mon–Fri**
> Did Fran get a lift in this morning? [Yes] [No]
> Did Lauren get a lift in this morning? [Yes] [No]

**9:00pm Mon–Fri**
> Did Fran get a lift home? [Yes] [No]
> Did Lauren get a lift home? [Yes] [No]
> Any costs today? (type a number or 0)

**Saturday 9:00am**
> Weekly summary + buttons to generate each friend's payment message

---

## Cost calculation

Same logic as your spreadsheet:
- You = 2 trip units per day (both ways)
- Each friend = 1 unit per trip they took
- Their share = (their units ÷ total units) × daily cost

---

## Running locally (optional)

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your values
python -m dotenv run python bot.py
```

Or just set the env vars in your shell and run `python bot.py`.
