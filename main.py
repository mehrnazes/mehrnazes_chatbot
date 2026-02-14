import os
import time
import logging
from collections import defaultdict

import requests
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

 
# ENV
 
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

CARD_NUMBER = "5859831080517518"
API_URL = "https://openrouter.ai/api/v1/chat/completions"

 
# LOGGING
 
logging.basicConfig(level=logging.INFO)

 
# FASTAPI APP
 
app = FastAPI()
telegram_app = Application.builder().token(BOT_TOKEN).build()

 
# STATE
 
user_memory = {}
report_waiting = {}
support_waiting = {}
user_requests = defaultdict(list)

RATE_LIMIT = 5
RATE_WINDOW = 10  # seconds

 
# AI QUERY
 
def query_openrouter(user_text, chat_history=None):
    if chat_history is None:
        chat_history = []

    messages = [
        {"role": "system", "content": "You are witty, playful, slightly blunt, reply in English or Persian as user types, keep replies short."}
    ]
    messages.extend(chat_history)
    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": "gpt-4o-mini",
        "messages": messages,
        "temperature": 0.8,
        "max_tokens": 150
    }

    try:
        r = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=20
        )
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logging.error(f"OpenRouter API error: {e}")
        return "یه مشکلی پیش اومده 😅"

 
# HANDLERS
 
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💬 Chat", callback_data="chat")],
        [InlineKeyboardButton("📩 Report", callback_data="report")],
        [InlineKeyboardButton("💖 Support", callback_data="support")]
    ]
    await update.message.reply_text(
        "سلام سلام 😎 من مِهرنازه‌ام!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "report":
        report_waiting[user_id] = True
        await query.edit_message_text("متن گزارشت رو بنویس")

    elif data == "support":
        support_waiting[user_id] = True
        await query.edit_message_text(
            f"شماره کارت:\n`{CARD_NUMBER}`\n\nبعدش مبلغ رو بفرست.",
            parse_mode="Markdown"
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

     
    # Rate limit
     
    now = time.time()
    user_requests[user_id] = [t for t in user_requests[user_id] if now - t < RATE_WINDOW]

    if len(user_requests[user_id]) >= RATE_LIMIT:
        await update.message.reply_text("آروم‌تر 😅")
        return
    user_requests[user_id].append(now)

     
    # Report
     
    if report_waiting.get(user_id):
        logging.info(f"REPORT {user_id}: {text}")
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"Report from {update.message.from_user.full_name}:\n{text}")
        await update.message.reply_text("ثبت شد ✅")
        report_waiting[user_id] = False
        return

     
    # Support
     
    if support_waiting.get(user_id):
        logging.info(f"PAYMENT {user_id}: {text}")
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"Payment from {update.message.from_user.full_name}:\n{text}")
        await update.message.reply_text("ثبت شد 🙌")
        support_waiting[user_id] = False
        return

     
    # Normal chat
     
    if user_id not in user_memory:
        user_memory[user_id] = []

    reply = query_openrouter(text, user_memory[user_id])
    user_memory[user_id].append({"role": "user", "content": text})
    user_memory[user_id].append({"role": "assistant", "content": reply})
    # Keep only last 10 messages
    user_memory[user_id] = user_memory[user_id][-10:]

    await update.message.reply_text(reply)

 
# REGISTER HANDLERS
 
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CallbackQueryHandler(button_handler))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

 
# WEBHOOK ROUTE
 
@app.post(f"/{BOT_TOKEN}")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

 
# STARTUP
 
@app.on_event("startup")
async def on_startup():
    await telegram_app.initialize()
    await telegram_app.bot.set_webhook(f"{WEBHOOK_URL}/{BOT_TOKEN}")
