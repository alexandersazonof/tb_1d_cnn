from telegram import Bot
import asyncio
from binance.spot import Spot
import joblib
from tensorflow.keras.models import load_model
import numpy as np
import time
from dotenv import load_dotenv
import os

load_dotenv()

TG_TOKEN = os.getenv('TG_TOKEN')
TG_CHAT_ID = os.getenv('TG_CHAT_ID')

BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_KEY_SECRET = os.getenv('BINANCE_KEY_SECRET')

MIN_ORDER_VALUE = float(os.getenv('MIN_ORDER_VALUE'))
FEES_PERCENT = float(os.getenv('FEES_PERCENT'))
PROFIT_PERCENT = float(os.getenv('PROFIT_PERCENT'))
AVAILABLE_PRICE_IMPACT = float(os.getenv('AVAILABLE_PRICE_IMPACT'))

# ----- TELEGRAM FUNCTIONS -----
async def send_message(message):
    bot = Bot(TG_TOKEN)
    await bot.send_message(chat_id=TG_CHAT_ID, text=message)

# ----- BINANCE SPOT FUNCTIONS -----
def create_spot_deal(
        symbol,
        # BUY OR SELL
        side,
        # LIMIT, MARKET, STOP_LOSS_LIMIT, TAKE_PROFIT_LIMIT
        type,
        quantity
):
    client = Spot(api_key=BINANCE_API_KEY, api_secret=BINANCE_KEY_SECRET)
    params = {
        'symbol': symbol,
        'side': side,
        'type': type,
        'quantity': quantity,
    }
    print(f'create_spot_deal: {params}')
    return client.new_order(**params)

def create_spot_limit_deal(
        symbol,
        # BUY OR SELL
        side,
        # LIMIT, MARKET, STOP_LOSS_LIMIT, TAKE_PROFIT_LIMIT
        type,
        # GTC, IOC, FOK
        timeInForce,
        quantity,
        price
):
    client = Spot(api_key=BINANCE_API_KEY, api_secret=BINANCE_KEY_SECRET)
    params = {
        'symbol': symbol,
        'side': side,
        'type': type,
        'timeInForce': timeInForce,
        'quantity': quantity,
        'price': price
    }
    print(f'create_spot_deal: {params}')
    return client.new_order(**params)

def get_order_info(
        symbol,
        orderId
):
    client = Spot(api_key=BINANCE_API_KEY, api_secret=BINANCE_KEY_SECRET)
    params = {
        'symbol': symbol,
        'orderId': orderId
    }
    client.get_order(**params)

def get_balance():
    client = Spot(api_key=BINANCE_API_KEY, api_secret=BINANCE_KEY_SECRET)

    account = client.account()
    for balance in account['balances']:
        if balance['asset'] == 'USDT':
            return balance['free']
    return 0

def cancel_order(
        symbol,
        orderId
):
    client = Spot(api_key=BINANCE_API_KEY, api_secret=BINANCE_KEY_SECRET)
    params = {
        'symbol': symbol,
        'orderId': orderId
    }
    client.cancel_order(**params)


def predict_price():
    # Загрузка модели
    model = load_model("data/modelV1.h5")

    # Загрузка масштабировщиков
    scaler = joblib.load('data/scaler.pkl')
    close_scaler = joblib.load('data/close_scaler.pkl')
    new_data = client.klines("BTCUSDT", "5m", limit=100)
    # Предположим, что new_data - это ваш новый набор данных
    features = np.array([list(item) for item in new_data])[:, 1:6]
    # Масштабирование данных
    scaled_features = scaler.transform(features)

    # Подготовка последних 60 точек данных
    last_60_points = scaled_features[-60:]
    last_60_points = np.reshape(last_60_points, (1, last_60_points.shape[0], last_60_points.shape[1]))

    # Прогнозирование следующей цены
    predicted_next_price = model.predict(last_60_points)
    predicted_next_price = close_scaler.inverse_transform(predicted_next_price)

    return predicted_next_price[0][0]


client = Spot()
print(client.time())

symbol = 'BTCUSDT'

def main_logic():
    traded = False
    # predict price
    predicted = float(predict_price())

    last_spot_price = float(client.klines(symbol, "1s", limit=1)[0][1])
    print('--------------------------------')
    print(f"Predict price: {predicted - 100}")
    print(f"Last spot price: {last_spot_price}")

    can_trade = last_spot_price < (predicted - 100)
    price_impact = (predicted - 100) - last_spot_price
    print(f'Can trade {can_trade}')
    print(f'Price impact {price_impact}')

    balance = get_balance()
    if float(balance) < MIN_ORDER_VALUE:
        print('BALANCE SMALL !!!!!!!!!!!')
        time.sleep(10)
        return False

    if can_trade and price_impact > AVAILABLE_PRICE_IMPACT:
        try:
            quantity = round(MIN_ORDER_VALUE / last_spot_price, 5)
            order = create_spot_deal(symbol, 'BUY', 'MARKET', quantity)
            print(order)
            order_quantity = order['fills'][0]['qty']
            order_price = float(order['fills'][0]['price'])

            traded = True
            new_order_price = round(order_price + (float(order_price) * PROFIT_PERCENT), 2)
            print(f'New order price: {new_order_price}')
            time.sleep(2)
            new_order = create_spot_limit_deal(symbol, 'SELL', 'LIMIT', 'GTC', order_quantity, new_order_price)
            print(f'New order price {new_order}')
        except Exception as e:
            print(e)
            asyncio.run(send_message(f'Error during trade {e}'))
            return True
        # send telegram message
        asyncio.run(send_message(f'--------OPEN ORDER-------\n'
                                 f'Last spot price: {last_spot_price}\n'
                                 f'Order price: {order_price}\n'
                                 f'New Order price: {new_order_price}\n'
                                 f'Predict price: {predicted - 100}\n'
                                 f'Quantity: {order_quantity}\n'
                                 f'Price impact: {price_impact}\n'
                                 f'Profit USD: {round((new_order_price - round(order_price, 2), 4) * float(order_quantity))}$\n'
                                 f'Profit %: {round((new_order_price / (float(last_spot_price) / 100)) - 100, 2)}%'
                                 ))

    print('--------------------------------')
    return traded

traded = False
while True:
    if traded:
        traded = False
        time.sleep(30)

    traded = main_logic()

    time.sleep(1)
