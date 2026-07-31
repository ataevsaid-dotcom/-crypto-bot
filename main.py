import logging
import requests

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ======================
# TELEGRAM BOT
# ======================

BOT_TOKEN = "8996509464:AAHvRs8cswkHVCSUpqe1
wsl1NzlVMJlwi4k"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)

COINS = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "bnb": "binancecoin",
    "xrp": "ripple",
}

# ======================
# START
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Привет! Я крипто-бот.\n\n"
        "Команды:\n"
        "/price btc — цена Bitcoin\n"
        "/price eth — цена Ethereum\n"
        "/price sol — цена Solana\n"
        "/price bnb — цена BNB\n"
        "/price xrp — цена XRP\n"
        "/all — все цены сразу"
    )
    await update.message.reply_text(text)


async def get_price(coin_id: str) -> float | None:
    """Получает текущую цену в USD через CoinGecko"""
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": coin_id, "vs_currencies": "usd"}
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data[coin_id]["usd"]
    except Exception as e:
        logging.error(f"Ошибка при получении цены {coin_id}: {e}")
        return None


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажи монету, например: /price btc")
        return

    symbol = context.args[0].lower()
    coin_id = COINS.get(symbol)

    if not coin_id:
        await update.message.reply_text(
            f"Не знаю монету «{symbol}».\n"
            f"Доступные: {', '.join(COINS.keys())}"
        )
        return

    price_usd = await get_price(coin_id)
    if price_usd is None:
        await update.message.reply_text("Не удалось получить цену. Попробуй позже.")
        return

    await update.message.reply_text(
        f"{symbol.upper()}: ${price_usd:,.2f}"
    )


async def all_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = []
    for symbol, coin_id in COINS.items():
        price_usd = await get_price(coin_id)
        if price_usd is not None:
            lines.append(f"{symbol.upper()}: ${price_usd:,.2f}")
        else:
            lines.append(f"{symbol.upper()}: ошибка")

    await update.message.reply_text("\n".join(lines))


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("all", all_prices))

    logging.info("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()