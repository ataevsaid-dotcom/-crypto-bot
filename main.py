"""
Крипто-бот для Telegram.

Функции:
  /price <монета> [валюта]   — цена, изменение за 24ч, капитализация
  /all [валюта]              — все отслеживаемые монеты
  /top [N]                   — топ N по капитализации
  /search <запрос>           — поиск монет
  /currencies                — список доступных валют
  /alert <монета> <цена> <above|below> — алерт о достижении цены
  /alerts                    — ваши активные алерты
  /cancelalert <№>           — удалить алерт

Источник данных: CoinGecko API (бесплатный, есть лимиты).
Токен бота берётся из переменной окружения BOT_TOKEN.
"""

import logging
import os
import time

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ======================
# КОНФИГУРАЦИЯ
# ======================

BASE_URL = "https://api.coingecko.com/api/v3"
CACHE_TTL = 30          # секунд жизни кэша цен
ALERT_CHECK_INTERVAL = 60  # период проверки алертов, секунд

# Отслеживаемые монеты: символ -> id в CoinGecko
COINS = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "bnb": "binancecoin",
    "xrp": "ripple",
    "ada": "cardano",
    "doge": "dogecoin",
    "ton": "the-open-network",
    "dot": "polkadot",
    "avax": "avalanche-2",
    "link": "chainlink",
    "ltc": "litecoin",
    "matic": "matic-network",
    "trx": "tron",
    "shib": "shiba-inu",
}

# Поддерживаемые фиатные валюты: код -> символ для отображения
CURRENCIES = {
    "usd": "$",
    "eur": "€",
    "rub": "₽",
    "gbp": "£",
    "jpy": "¥",
    "uah": "₴",
    "kzt": "₸",
    "try": "₺",
}

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class CoinGeckoError(Exception):
    """Ошибка при работе с API CoinGecko."""


# ======================
# КЭШ (защита от лимитов API)
# ======================

_cache: dict = {}


def _cache_get(key):
    entry = _cache.get(key)
    if entry and time.monotonic() - entry[0] < CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key, value):
    _cache[key] = (time.monotonic(), value)


# ======================
# ФОРМАТИРОВАНИЕ
# ======================

def cur_symbol(vs: str) -> str:
    return CURRENCIES.get(vs, vs.upper())


def fmt_price(p):
    if p is None:
        return "н/д"
    if p >= 1:
        return f"{p:,.2f}"
    if p >= 0.01:
        return f"{p:,.4f}"
    return f"{p:,.8f}"


def fmt_large(n):
    if n is None:
        return "н/д"
    for unit in ("", "K", "M", "B", "T"):
        if abs(n) < 1000:
            return f"{n:.2f}{unit}"
        n /= 1000
    return f"{n:.2f}Q"


def fmt_change(pct):
    if pct is None:
        return "н/д"
    arrow = "🟢" if pct >= 0 else "🔴"
    return f"{arrow} {pct:+.2f}%"


# ======================
# API COINGECKO
# ======================

async def api_get(client: httpx.AsyncClient, path: str, params: dict):
    url = f"{BASE_URL}{path}"
    try:
        r = await client.get(url, params=params)
    except httpx.HTTPError as e:
        raise CoinGeckoError(f"Сетевая ошибка: {e}") from e
    if r.status_code == 429:
        raise CoinGeckoError(
            "Слишком много запросов. CoinGecko ограничил частоту, попробуйте позже."
        )
    if r.status_code >= 400:
        raise CoinGeckoError(f"HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError as e:
        raise CoinGeckoError("Некорректный ответ API") from e


async def get_simple_prices(client, ids, vs):
    """Цены, капитализация и изменение за 24ч одним запросом."""
    key = ("prices", tuple(sorted(ids)), vs)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    params = {
        "ids": ",".join(ids),
        "vs_currencies": vs,
        "include_market_cap": "true",
        "include_24hr_change": "true",
    }
    data = await api_get(client, "/simple/price", params)
    result = {}
    for cid in ids:
        d = data.get(cid)
        if d:
            result[cid] = {
                "price": d.get(vs),
                "market_cap": d.get(f"{vs}_market_cap"),
                "change_24h": d.get(f"{vs}_24h_change"),
            }
    _cache_set(key, result)
    return result


async def get_top_markets(client, vs, limit):
    key = ("top", vs, limit)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    params = {
        "vs_currency": vs,
        "order": "market_cap_desc",
        "per_page": limit,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "24h",
    }
    data = await api_get(client, "/coins/markets", params)
    _cache_set(key, data)
    return data


async def search_coins(client, query):
    key = ("search", query.lower())
    cached = _cache_get(key)
    if cached is not None:
        return cached
    data = await api_get(client, "/search", {"query": query})
    coins = data.get("coins", [])[:10]
    _cache_set(key, coins)
    return coins


async def resolve_coin(client, symbol):
    """Возвращает id монеты по символу или id, либо None."""
    symbol = symbol.lower()
    if symbol in COINS:
        return COINS[symbol]
    # пробуем использовать аргумент как готовый id CoinGecko
    try:
        data = await get_simple_prices(client, [symbol], "usd")
        if data.get(symbol, {}).get("price") is not None:
            return symbol
    except CoinGeckoError:
        pass
    # ищем по символу
    try:
        results = await search_coins(client, symbol)
    except CoinGeckoError:
        return None
    for r in results:
        if r.get("symbol", "").lower() == symbol:
            return r.get("id")
    return None


# ======================
# ХЕНДЛЕРЫ
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coins = ", ".join(sorted(COINS.keys()))
    text = (
        "👋 Привет! Я крипто-бот.\n\n"
        "📌 Команды:\n"
        "/price <монета> [валюта] — цена, 24ч, капитализация\n"
        "/all [валюта] — все отслеживаемые монеты\n"
        "/top [N] — топ N по капитализации\n"
        "/search <запрос> — поиск монет\n"
        "/currencies — доступные валюты\n\n"
        "🔔 Алерты:\n"
        "/alert btc 100000 above — уведомить, когда BTC ≥ $100000\n"
        "/alert eth 2000 below — уведомить, когда ETH ≤ $2000\n"
        "/alerts — ваши алерты\n"
        "/cancelalert <№> — удалить алерт\n\n"
        f"Монеты: {coins}"
    )
    await update.message.reply_text(text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def currencies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["💱 Доступные валюты:"]
    for code, sym in CURRENCIES.items():
        lines.append(f"{sym} {code.upper()}")
    lines.append("\nПример: /price btc eur")
    await update.message.reply_text("\n".join(lines))


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = context.bot_data.get("client")
    if not context.args:
        await update.message.reply_text("Использование: /price btc [usd|eur|rub]")
        return
    symbol = context.args[0].lower()
    vs = context.args[1].lower() if len(context.args) > 1 else "usd"

    coin_id = await resolve_coin(client, symbol)
    if not coin_id:
        await update.message.reply_text(
            f"Монета «{symbol}» не найдена. Попробуйте /search {symbol}"
        )
        return
    try:
        data = await get_simple_prices(client, [coin_id], vs)
    except CoinGeckoError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return
    info = data.get(coin_id)
    if not info or info.get("price") is None:
        await update.message.reply_text("Не удалось получить цену. Попробуйте позже.")
        return
    cs = cur_symbol(vs)
    text = (
        f"🪙 {symbol.upper()}\n"
        f"💵 Цена: {cs}{fmt_price(info['price'])}\n"
        f"📈 24ч: {fmt_change(info.get('change_24h'))}\n"
    )
    if info.get("market_cap"):
        text += f"🏦 Капитализация: {cs}{fmt_large(info['market_cap'])}\n"
    await update.message.reply_text(text)


async def all_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = context.bot_data.get("client")
    vs = context.args[0].lower() if context.args else "usd"
    ids = list(COINS.values())
    try:
        data = await get_simple_prices(client, ids, vs)
    except CoinGeckoError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return
    cs = cur_symbol(vs)
    lines = [f"📊 Цены ({vs.upper()}):"]
    for sym, cid in COINS.items():
        info = data.get(cid)
        if info and info.get("price") is not None:
            lines.append(
                f"{sym.upper()}: {cs}{fmt_price(info['price'])} "
                f"{fmt_change(info.get('change_24h'))}"
            )
        else:
            lines.append(f"{sym.upper()}: ошибка")
    await update.message.reply_text("\n".join(lines))


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = context.bot_data.get("client")
    try:
        n = int(context.args[0]) if context.args else 10
    except ValueError:
        n = 10
    n = max(1, min(n, 50))
    try:
        markets = await get_top_markets(client, "usd", n)
    except CoinGeckoError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return
    lines = [f"🏆 Топ-{n} по капитализации:"]
    for i, m in enumerate(markets, 1):
        sym = m.get("symbol", "?").upper()
        price = m.get("current_price")
        ch = m.get("price_change_percentage_24h")
        lines.append(f"{i}. {sym}: ${fmt_price(price)} {fmt_change(ch)}")
    await update.message.reply_text("\n".join(lines))


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = context.bot_data.get("client")
    if not context.args:
        await update.message.reply_text("Использование: /search doge")
        return
    query = " ".join(context.args)
    try:
        coins = await search_coins(client, query)
    except CoinGeckoError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return
    if not coins:
        await update.message.reply_text("Ничего не найдено.")
        return
    lines = [f"🔍 Результаты по «{query}»:"]
    for c in coins[:5]:
        rank = c.get("market_cap_rank") or "—"
        lines.append(
            f"• {c.get('name')} ({c.get('symbol', '').upper()}) — "
            f"ранг {rank} — id: {c.get('id')}"
        )
    lines.append("\nid можно использовать в /price, например: /price bitcoin")
    await update.message.reply_text("\n".join(lines))


# ======================
# АЛЕРТЫ
# ======================

alerts: dict = {}          # id -> {chat_id, coin_id, symbol, target, direction}
_alert_counter = 0


async def alert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _alert_counter
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Использование: /alert btc 100000 above\n"
            "above — выше, below — ниже"
        )
        return
    symbol = args[0].lower()
    try:
        target = float(args[1])
    except ValueError:
        await update.message.reply_text("Цена должна быть числом.")
        return
    direction = args[2].lower()
    if direction not in ("above", "below"):
        await update.message.reply_text("Направление: above или below.")
        return
    client = context.bot_data.get("client")
    coin_id = await resolve_coin(client, symbol)
    if not coin_id:
        await update.message.reply_text(f"Монета «{symbol}» не найдена.")
        return
    _alert_counter += 1
    aid = _alert_counter
    alerts[aid] = {
        "chat_id": update.effective_chat.id,
        "coin_id": coin_id,
        "symbol": symbol,
        "target": target,
        "direction": direction,
    }
    word = "выше" if direction == "above" else "ниже"
    await update.message.reply_text(
        f"✅ Алерт #{aid} создан: {symbol.upper()} {word} ${target:,.2f}"
    )


async def alerts_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    my = {aid: a for aid, a in alerts.items() if a["chat_id"] == chat_id}
    if not my:
        await update.message.reply_text("У вас нет активных алертов.")
        return
    lines = ["🔔 Ваши алерты:"]
    for aid, a in my.items():
        d = "выше" if a["direction"] == "above" else "ниже"
        lines.append(f"#{aid}: {a['symbol'].upper()} {d} ${a['target']:,.2f}")
    await update.message.reply_text("\n".join(lines))


async def cancel_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Использование: /cancelalert 1")
        return
    try:
        aid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Укажите номер алерта.")
        return
    a = alerts.get(aid)
    if not a or a["chat_id"] != chat_id:
        await update.message.reply_text("Алерт не найден.")
        return
    del alerts[aid]
    await update.message.reply_text(f"Алерт #{aid} удалён.")


async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    """Периодическая задача: проверяет все алерты одним запросом."""
    if not alerts:
        return
    client = context.bot_data.get("client")
    if not client:
        return
    ids = list({a["coin_id"] for a in alerts.values()})
    try:
        prices = await get_simple_prices(client, ids, "usd")
    except CoinGeckoError:
        return
    to_remove = []
    for aid, a in list(alerts.items()):
        info = prices.get(a["coin_id"])
        if not info or info.get("price") is None:
            continue
        cur = info["price"]
        triggered = (
            (a["direction"] == "above" and cur >= a["target"])
            or (a["direction"] == "below" and cur <= a["target"])
        )
        if triggered:
            sign = "≥" if a["direction"] == "above" else "≤"
            try:
                await context.bot.send_message(
                    chat_id=a["chat_id"],
                    text=(
                        f"🔔 Алерт #{aid} сработал!\n"
                        f"{a['symbol'].upper()}: текущая ${fmt_price(cur)} "
                        f"{sign} целевой ${a['target']:,.2f}"
                    ),
                )
            except Exception as e:  # noqa: BLE001
                logger.error("Не удалось отправить алерт #%s: %s", aid, e)
            to_remove.append(aid)
    for aid in to_remove:
        alerts.pop(aid, None)


# ======================
# ОШИБКИ И ЖИЗНЕННЫЙ ЦИКЛ
# ======================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Ошибка при обработке апдейта: %s", context.error)


async def post_init(app: Application):
    app.bot_data["client"] = httpx.AsyncClient(timeout=15.0)
    logger.info("HTTP-клиент создан")


async def post_shutdown(app: Application):
    client = app.bot_data.get("client")
    if client:
        await client.aclose()
        logger.info("HTTP-клиент закрыт")


# ======================
# ТОЧКА ВХОДА
# ======================

def main():
    token = os.environ.get("")
    if not token:
        raise SystemExit(
            "Переменная окружения BOT_TOKEN не задана. "
            "Получите токен у @BotFather и экспортируйте BOT_TOKEN."
        )

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("all", all_prices))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("currencies", currencies))
    app.add_handler(CommandHandler("alert", alert_cmd))
    app.add_handler(CommandHandler("alerts", alerts_list))
    app.add_handler(CommandHandler("cancelalert", cancel_alert))

    app.add_error_handler(error_handler)

    # Периодическая проверка алертов
    app.job_queue.run_repeating(
        check_alerts, interval=ALERT_CHECK_INTERVAL, first=15
    )

    logger.info("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()