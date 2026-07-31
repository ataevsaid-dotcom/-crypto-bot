from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ВСТАВЬ СЮДА СВОЙ НОВЫЙ ТОКЕН
TOKEN = "ВСТАВЬ_СВОЙ_НОВЫЙ_ТОКЕН"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот для анализа криптовалют.\n\n"
        "Пока я умею только отвечать на команду /start.\n"
        "Скоро я научусь анализировать BTC, ETH и другие монеты."
    )

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()