import asyncio
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.conf import settings
from .models import FuturesOrders
import requests

class FuturesChartSocket(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_authenticated:
            await self.accept()
        else:
            await self.close()

    async def send_data(self):
        while True:
            open_orders = await self.get_open_futures_orders()
            data = []
            errors = []
            for order in open_orders:
                # --- amount parsing ---
                try:
                    amount = float(order.amount.split()[0]) if isinstance(order.amount, str) else float(order.amount)
                except Exception:
                    errors.append(f"amount نامعتبر برای معامله {order.id} ({order.amount})")
                    amount = 0
                # --- pair parsing ---
                try:
                    base, quote = order.pair[:-4], order.pair[-4:]
                    if not base or not quote:
                        raise ValueError
                except Exception:
                    errors.append(f"pair نامعتبر برای معامله {order.id} ({order.pair})")
                    base, quote = '', ''
                # --- get price ---
                current_price = 0
                if base and quote:
                    current_price = await self.get_market_price(order.pair)
                    if current_price == 0:
                        errors.append(f"قیمت لحظه‌ای برای {order.pair} دریافت نشد یا نامعتبر است.")
                # --- PnL calculation ---
                pnl, pnl_percent = self.calculate_futures_pnl(order, current_price, amount)
                data.append({
                    "id": order.id,
                    "pair": order.pair,
                    "type": order.type,
                    "amount": order.amount,
                    "entryPrice": order.entryPrice,
                    "marketPrice": current_price,
                    "leverage": order.leverage,
                    "pnl": pnl,
                    "pnl_percent": pnl_percent,
                })
            await self.send_json({"futures": data, "errors": errors})
            await asyncio.sleep(5)

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            while True:
                await asyncio.ensure_future(self.send_data())

    async def disconnect(self, close_code):
        await self.close()

    @database_sync_to_async
    def get_open_futures_orders(self):
        return list(FuturesOrders.objects.filter(usr_id=self.user.id, complete=False))

    async def get_market_price(self, pair):
        base, quote = pair[:-4], pair[-4:]
        url = f"https://min-api.cryptocompare.com/data/price?fsym={base}&tsyms={quote}"
        try:
            response = requests.get(url, timeout=5)
            data = response.json()
            return float(data.get(quote, 0))
        except Exception:
            return 0.0

    def calculate_futures_pnl(self, order, market_price, amount):
        entry = order.entryPrice
        leverage = order.leverage
        pnl = 0
        pnl_percent = 0
        if entry and market_price and leverage and amount:
            if order.type.lower() == "long":
                pnl = (market_price - entry) * amount * leverage
                pnl_percent = ((market_price - entry) / entry) * leverage * 100
            elif order.type.lower() == "short":
                pnl = (entry - market_price) * amount * leverage
                pnl_percent = ((entry - market_price) / entry) * leverage * 100
        return round(pnl, 4), round(pnl_percent, 2) 