# -crypto-bot

Telegram-бот для отслеживания цен криптовалют. Данные — CoinGecko API.

## Возможности

- Цена монеты с изменением за 24ч и капитализацией (`/price`)
- Все отслеживаемые монеты (`/all`)
- Топ по капитализации (`/top`)
- Поиск монет (`/search`)
- Алерты о достижении цены (`/alert`, `/alerts`, `/cancelalert`)
- Выбор фиатной валюты (USD, EUR, RUB и др.)

## Запуск локально

```bash
pip install -r requirements.txt
export BOT_TOKEN="ВАШ_ТОКЕН"
python main.py