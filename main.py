import logging
import time
from datetime import datetime
from io import BytesIO

import httpx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ======================
# CONFIG
# ======================

BOT_TOKEN = "8996509464:AAEkrX-qoyTix2x1Vz5zGp_7uUFPHJ1aLQQ"
CACHE_TTL = 60
API_URL = "https://api.coingecko.com/api/v3/simple/price"
CHART_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"

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
# CHART
# ======================

def build_chart(symbol: str, days: int, prices: list) -> BytesIO:
    times = [datetime.fromtimestamp(p[0] / 1000) for p in prices]
    values = [p[1] for p in prices]

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=110)

    color = "#26a69a" if values[-1] >= values[0] else "#ef5350"
    ax.plot(times, values, color=color, linewidth=1.6)
    ax.fill_between(times, values, min(values), color=color, alpha=0.12)

    ax.set_title(f"{symbol.upper()} / USD — {days}d", fontsize=14, pad=12)
    ax.tick_params(colors="#9aa4b2")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.grid(alpha=0.15)
    fig.autofmt_xdate()
    fig.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf


async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажи монету, например: /chart btc или /chart btc 30")
        return

    symbol = context.args[0].lower()
    coin_id = COINS.get(symbol)
    if not coin_id:
        await update.message.reply_text(
            f"Не знаю монету «{symbol}».\n"
            f"Доступные: {', '.join(COINS.keys())}"
        )
        return

    days = 7
    if len(context.args) > 1:
        try:
            days = min(max(int(context.args[1]), 1), 365)
        except ValueError:
            days = 7

    await update.message.chat.send_action("upload_photo")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                CHART_URL.format(coin_id=coin_id),
                params={"vs_currency": "usd", "days": days},
            )
            response.raise_for_status()
            prices = response.json()["prices"]
    except Exception as e:
        logging.error("Chart error: %s", e)
        prices = []

    if not prices:
        await update.message.reply_text("Не удалось получить график. Попробуй позже.")
        return

    buf = build_chart(symbol, days, prices)
    await update.message.reply_photo(buf, filename=f"{symbol}_{days}d.png")


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
        "/all — все цены сразу\n"
        "/chart btc — график за 7 дней\n"
        "/chart btc 30 — график за 30 дней\n\n"
        "Показываю цену в $ и ₽ + изменение за 24 часа 📈"
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
        await update.message.reply_text("Не удастся получить цены. Попробуй позже.")
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
        BotCommand("chart", "график цены, напр. /chart btc"),
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
    app.add_handler(CommandHandler("chart", chart))

    logging.info("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()