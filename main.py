import os
import logging
import requests
from collections import defaultdict
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
CARD_NUMBER = "5859831080517518"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Railway URL

 
# LOGGING
 
logging.basicConfig(level=logging.INFO)

 
# STATE
 
user_memory = {}
report_waiting = {}
support_waiting = {}
user_requests = defaultdict(list)
RATE_LIMIT = 5
RATE_WINDOW = 10

 
# AI
 
API_URL = "https://openrouter.ai/api/v1/chat/completions"

def query_openrouter(user_text, chat_history=None):
    if chat_history is None:
        chat_history = []

    messages = [
        {
            "role": "system",
            "content": (
                "You are Mehrnaz, a witty, playful, slightly blunt assistant. "
                "You respond honestly, use emojis, humor, casual language, "
                "and sometimes a little sarcasm. "
                "Keep replies short (1-2 sentences). "
                "Reply in the same language as the user (English or Persian). "
                "Never narrate or give instructions."
            )
        }
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
            timeout=15
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
        "سلام 😎 من مهرنازم!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "report":
        report_waiting[user_id] = True
        await query.edit_message_text("لطفا متن گزارشت رو بنویس")

    elif data == "support":
        support_waiting[user_id] = True
        await query.edit_message_text(
            f"شماره کارت:\n`{CARD_NUMBER}`\n\nبعدش مبلغ رو بفرست.",
            parse_mode="Markdown"
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    text = update.message.text.strip()

    # RATE LIMIT
    import time
    now = time.time()
    user_requests[user_id] = [t for t in user_requests[user_id] if now - t < RATE_WINDOW]
    if len(user_requests[user_id]) >= RATE_LIMIT:
        await update.message.reply_text("آروم‌تر 😅 لطفا چند ثانیه صبر کن")
        return
    user_requests[user_id].append(now)

    # REPORT
    if report_waiting.get(user_id):
        logging.info(f"REPORT {user_id}: {text}")
        await context.bot.send_message(ADMIN_CHAT_ID, f"Report from {user.full_name} ({user.id}):\n{text}")
        await update.message.reply_text("گزارش شما ثبت شد ✅")
        report_waiting[user_id] = False
        return

    # SUPPORT
    if support_waiting.get(user_id):
        logging.info(f"SUPPORT {user_id}: {text}")
        await context.bot.send_message(ADMIN_CHAT_ID, f"Support payment from {user.full_name} ({user.id}):\n{text}")
        await update.message.reply_text("ثبت شد 🙌 ممنون!")
        support_waiting[user_id] = False
        return

    # NORMAL CHAT
    if user_id not in user_memory:
        user_memory[user_id] = []

    reply = query_openrouter(text, user_memory[user_id])
    user_memory[user_id].append({"role": "user", "content": text})
    user_memory[user_id].append({"role": "assistant", "content": reply})
    user_memory[user_id] = user_memory[user_id][-10:]

    await update.message.reply_text(reply)

 
# TELEGRAM APP

telegram_app = Application.builder().token(BOT_TOKEN).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CallbackQueryHandler(button_handler))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


# FASTAPI WEBHOOK

app = FastAPI()


@app.on_event("startup")
async def on_startup():
    # Properly initialize PTB
    await telegram_app.initialize()
    await telegram_app.start()

    # Set webhook
    url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
    logging.info(f"Setting webhook to: {url}")
    await telegram_app.bot.set_webhook(url)


@app.on_event("shutdown")
async def on_shutdown():
    # Graceful shutdown (important on Railway)
    await telegram_app.stop()
    await telegram_app.shutdown()


@app.post(f"/{BOT_TOKEN}")
async def telegram_webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, telegram_app.bot)

    # Now this will NOT crash
    await telegram_app.process_update(update)

    return {"ok": True}

 
# RUN with Uvicorn
 
# Railway automatically runs:
# uvicorn main:app --host 0.0.0.0 --port $PORT
