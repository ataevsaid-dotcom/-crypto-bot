import logging
import time

import httpx
from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ======================
# CONFIG
# ======================

BOT_TOKEN = "ВСТАВЬТЕ_ВАШ_ТОКЕН_СЮДА"
CACHE_TTL = 60
API_URL = "https://api.coingecko.com/api/v3/simple/price"

COINS = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "bnb": "binancecoin",
    "xrp": "ripple",
}

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)

# ======================
# API + CACHE
# ======================

_cache: dict = {"time": 0.0, "data": None}


async def get_prices() -> dict | None:
    """Цены всех монет одним запросом, кэш на CACHE_TTL секунд."""
    now = time.monotonic()
    if _cache["data"] is not None and now - _cache["time"] < CACHE_TTL:
        return _cache["data"]

    params = {
        "ids": ",".join(COINS.values()),
        "vs_currencies": "usd,rub",
        "include_24hr_change": "true",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(API_URL, params=params)
            response.raise_for_status()
            data = response.json()
        _cache["time"] = now
        _cache["data"] = data
        return data
    except Exception as e:
        logging.error("CoinGecko error: %s", e)
        return _cache["data"]


def format_price(symbol: str, info: dict) -> str:
    usd = info["usd"]
    rub = info.get("rub")
    change = info.get("usd_24h_change")

    text = f"{symbol.upper()}: ${usd:,.2f}"
    if rub is not None:
        text += f" / {rub:,.0f} ₽"
    if change is not None:
        emoji = "📈" if change >= 0 else "📉"
        text += f" {emoji} {change:+.2f}% (24h)"
    return text


# ======================
# HANDLERS
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Привет! Я крипто-бот. 🤖\n\n"
        "Команды:\n"
        "/price btc — цена Bitcoin\n"
        "/price eth — цена Ethereum\n"
        "/price sol — цена Solana\n"
        "/price bnb — цена BNB\n"
        "/price xrp — цена XRP\n"
        "/all — все цены сразу\n\n"
        "Показываю цену в $ и ₽ + изменение за 24 часа 📈📉"
    )
    await update.message.reply_text(text)


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

    data = await get_prices()
    info = (data or {}).get(coin_id)
    if not info:
        await update.message.reply_text("Не удалось получить цену. Попробуй позже.")
        return

    await update.message.reply_text(format_price(symbol, info))


async def all_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = await get_prices()
    if not data:
        await update.message.reply_text("Не удалось получить цены. Попробуй позже.")
        return

    lines = []
    for symbol, coin_id in COINS.items():
        info = data.get(coin_id)
        lines.append(format_price(symbol, info) if info else f"{symbol.upper()}: ошибка")

    await update.message.reply_text("\n".join(lines))


# ======================
# MAIN
# ======================

async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "запуск и справка"),
        BotCommand("price", "цена монеты, напр. /price btc"),
        BotCommand("all", "все цены сразу"),
    ])


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("all", all_prices))

    logging.info("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()