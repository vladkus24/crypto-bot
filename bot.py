import json
import requests
from aiogram import Bot, Dispatcher
import asyncio
from collections import defaultdict
from config import TELEGRAM_BOT_TOKEN, CHANNEL_ID, HELIUS_URL, BIRDEYE_API_KEY, BIRDEYE_URL, MIN_BUY_AMOUNT_SOL, MIN_WALLETS_TRIGGER

# Загружаем кошельки
with open("wallets_clean.json", "r", encoding="utf-8") as f:
    WALLETS = {w["address"]: w["name"] for w in json.load(f)}

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

async def send_signal(token_name, token_symbol, token_address, market_cap, buyers):
    """Отправка сигнала в канал"""
    msg = f"""
<b>{len(buyers)} Wallets Have Bought {token_name} ({token_symbol})</b>
<code>{token_address}</code>

<a href="https://app.axiom.xyz/token/{token_address}">Open on AXIOM</a>
Market Cap: {market_cap}

<b>Buyers:</b>
""" 
    for buyer, amount in buyers.items():
        msg += f"\n{buyer}: {amount} SOL"

    await bot.send_message(CHANNEL_ID, msg, parse_mode="HTML", disable_web_page_preview=True)

def get_token_info(mint_address):
    """Получаем имя, символ, маркеткап токена через Birdeye"""
    headers = {"X-API-KEY": BIRDEYE_API_KEY}
    url = f"{BIRDEYE_URL}/token_metadata?address={mint_address}"
    resp = requests.get(url, headers=headers).json()
    if "data" not in resp:
        return "Unknown", "???", "N/A"
    data = resp["data"]
    name = data.get("name", "Unknown")
    symbol = data.get("symbol", "???")
    market_cap = data.get("market_cap", "N/A")
    if isinstance(market_cap, (int, float)):
        market_cap = f"{market_cap:,.0f}"
    return name, symbol, market_cap

async def monitor():
    seen_signatures = set()
    token_buys = defaultdict(dict)  # {mint: {wallet_name: amount_sol}}

    while True:
        for address, name in WALLETS.items():
            payload = {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "getSignaturesForAddress",
                "params": [address, {"limit": 5}]
            }
            try:
                resp = requests.post(HELIUS_URL, json=payload).json()
                if "result" not in resp:
                    continue
                for tx in resp["result"]:
                    sig = tx["signature"]
                    if sig in seen_signatures:
                        continue
                    seen_signatures.add(sig)

                    # получаем детали транзакции
                    tx_payload = {
                        "jsonrpc": "2.0",
                        "id": "2",
                        "method": "getTransaction",
                        "params": [sig, {"encoding": "jsonParsed"}]
                    }
                    tx_data = requests.post(HELIUS_URL, json=tx_payload).json()

                    if "result" not in tx_data or not tx_data["result"]:
                        continue

                    meta = tx_data["result"]["meta"]
                    if not meta:
                        continue

                    # Проверяем изменение баланса SOL
                    pre_bal = meta.get("preBalances", [])[0] if meta.get("preBalances") else 0
                    post_bal = meta.get("postBalances", [])[0] if meta.get("postBalances") else 0
                    sol_change = (pre_bal - post_bal) / 1e9

                    if sol_change < MIN_BUY_AMOUNT_SOL:
                        continue

                    # Проверяем токеновые переводы
                    token_balances = meta.get("postTokenBalances", [])
                    if not token_balances:
                        continue

                    token_address = token_balances[0].get("mint")
                    if not token_address:
                        continue

                    # Добавляем покупку
                    token_buys[token_address][name] = round(sol_change, 3)

                    # Если купило >= MIN_WALLETS_TRIGGER разных кошельков → сигнал
                    if len(token_buys[token_address]) >= MIN_WALLETS_TRIGGER:
                        token_name, token_symbol, market_cap = get_token_info(token_address)
                        await send_signal(token_name, token_symbol, token_address, market_cap, token_buys[token_address])
                        token_buys[token_address] = {}  # сбрасываем после сигнала

            except Exception as e:
                print("Ошибка при опросе:", e)

        await asyncio.sleep(10)  # каждые 10 секунд

async def main():
    asyncio.create_task(monitor())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
