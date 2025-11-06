from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ربات فعال است.")

if __name__ == "__main__":
    BOT_TOKEN = "8280505234:AAFYDaH1QrR5UCgSWzEYNAzZWekvxSdMxak"
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()