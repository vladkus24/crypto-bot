import json
import requests
import asyncio
from collections import defaultdict
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from config import TELEGRAM_BOT_TOKEN, CHANNEL_ID, HELIUS_URL, MIN_BUY_AMOUNT_SOL, MIN_WALLETS_TRIGGER, BIRDEYE_API_KEY, BIRDEYE_URL
from database import init_db, save_signal, get_all_signals

# Загружаем кошельки
with open("wallets_clean.json", "r", encoding="utf-8") as f:
    WALLETS = {w["address"]: w["name"] for w in json.load(f)}

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()


async def send_signal(token_name, token_symbol, token_address, market_cap, buyers):
    """Отправка сигнала в канал"""
    buyers_text = "\n".join([f"{buyer}: {amount} SOL" for buyer, amount in buyers.items()])

    msg = f"""
<b>{len(buyers)} Wallets Have Bought {token_name} ({token_symbol})</b>
<code>{token_address}</code>

<a href="https://app.axiom.xyz/token/{token_address}">Open on AXIOM</a> | 
<a href="https://birdeye.so/token/{token_address}?chain=solana">Birdeye</a> | 
<a href="https://solscan.io/token/{token_address}">Solscan</a>

Market Cap: {market_cap}

<b>Buyers:</b>
{buyers_text}
"""

    # Сохраняем сигнал в БД
    try:
        mc = float(str(market_cap).replace(",", "").replace("K", "000").replace("M", "000000")) if isinstance(market_cap, str) and market_cap != "🚀 Soon after launch" else 0
        save_signal(token_address, token_name, token_symbol, mc)
    except Exception as e:
        print("Ошибка при сохранении сигнала:", e)

    await bot.send_message(CHANNEL_ID, msg, parse_mode="HTML", disable_web_page_preview=True)


def get_token_info(mint_address):
    """Получаем имя, символ, маркеткап токена через Birdeye"""
    headers = {"X-API-KEY": BIRDEYE_API_KEY}
    url = f"{BIRDEYE_URL}/token_metadata?address={mint_address}"
    try:
        resp = requests.get(url, headers=headers).json()
        if "data" not in resp or not resp["data"]:
            return "Unknown", "???", "🚀 Soon after launch"

        data = resp["data"]
        name = data.get("name", "Unknown")
        symbol = data.get("symbol", "???")
        market_cap = data.get("market_cap")

        if isinstance(market_cap, (int, float)):
            market_cap = f"{market_cap:,.0f}"
        else:
            market_cap = "🚀 Soon after launch"

        return name, symbol, market_cap
    except Exception as e:
        print("Ошибка при получении данных из Birdeye:", e)
        return "Unknown", "???", "🚀 Soon after launch"


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

                    # Проверяем изменение SOL
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

                    # Сохраняем покупку
                    token_buys[token_address][name] = round(sol_change, 3)

                    # Если купило ≥ MIN_WALLETS_TRIGGER → сигнал
                    if len(token_buys[token_address]) >= MIN_WALLETS_TRIGGER:
                        token_name, token_symbol, market_cap = get_token_info(token_address)
                        await send_signal(token_name, token_symbol, token_address, market_cap, token_buys[token_address])
                        token_buys[token_address] = {}  # сбрасываем после сигнала

            except Exception as e:
                print("Ошибка при опросе Helius:", e)

        await asyncio.sleep(10)  # каждые 10 секунд проверяем


@dp.message(Command("stats"))
async def stats_handler(message: types.Message):
    """Выдаёт ТОП-10 сигналов по росту маркет-капа"""
    signals = get_all_signals()
    results = []

    for addr, name, symbol, cap_signal, ts in signals:
        token_name, token_symbol, cap_now = get_token_info(addr)
        if cap_now == "🚀 Soon after launch" or cap_signal == 0:
            continue
        try:
            cap_now_val = float(str(cap_now).replace(",", ""))
            x = cap_now_val / cap_signal if cap_signal > 0 else 0
            results.append((token_name, token_symbol, cap_signal, cap_now_val, x))
        except:
            continue

    results = sorted(results, key=lambda x: x[4], reverse=True)[:10]

    if not results:
        await message.answer("Пока нет сохранённых сигналов 📉")
        return

    msg = "📊 <b>ТОП-10 сигналов</b>\n"
    for i, (name, symbol, cap1, cap2, x) in enumerate(results, start=1):
        msg += f"\n{i}. {name} ({symbol})\n   {cap1:,.0f} → {cap2:,.0f} (x{x:.2f})"

    await message.answer(msg, parse_mode="HTML")


async def main():
    init_db()

    # Регистрируем команды
    await bot.set_my_commands([
        types.BotCommand(command="stats", description="Показать ТОП-10 сигналов")
    ])

    # Запускаем мониторинг и бота
    asyncio.create_task(monitor())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
