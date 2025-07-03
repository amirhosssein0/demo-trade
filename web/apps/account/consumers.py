import asyncio

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from core.charts import Charts
from core.utils import calc_equivalent, get_crypto_compare, pretify
from django.db.models import F, Sum
from exchange.models import Portfolio, TradeHistory
from limit_order.models import LimitOrders
from future.models import FuturesOrders


class ChartSocket(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_authenticated:
            await self.accept()
        else:
            self.close()

    async def send_data(self):
        portfolio = await self.get_portfolio()
        trades = await self.get_trades()

        dictionary = {}

        orderMargin = await self.get_orders()
        chart = Charts(portfolio, trades, orderMargin)
        assetAllocation = chart.asset_allocation()
        pnl = chart.profit_loss()

        dictionary["assetAllocation"] = assetAllocation
        dictionary["pnl"] = pnl

        await self.send_json(dictionary)
        await asyncio.sleep(60)

    async def disconnect(self, close_code):
        self.close()

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            while True:
                await asyncio.ensure_future(self.send_data())

    @database_sync_to_async
    def get_portfolio(self):
        return list(
            Portfolio.objects.all().filter(
                usr_id=self.user.id,
                marketType="spot",
            )
        )

    @database_sync_to_async
    def get_trades(self):
        return list(
            TradeHistory.objects.all().filter(
                usr_id=self.user.id,
                complete=True,
            )
        )

    @database_sync_to_async
    def get_orders(self):
        return list(
            LimitOrders.objects.all().filter(
                usr_id=self.user.id,
                amount__gt=0,
            )
        )


class WalletSocket(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_authenticated:
            await self.accept()
        else:
            self.close()

    async def send_data(self):
        domain = "https://cryptocompare.com"

        cryptocompare = get_crypto_compare()
        portfolio = await self.get_portfolio()
        dictionary = {}
        totalMargin = sum([calc_equivalent(item.cryptoName, "USDT", item.amount)[1] for item in portfolio])

        assets = {}
        for item in portfolio:
            assets[item.cryptoName] = float(item.amount)

        array = []
        data = cryptocompare.get_price(list(assets.keys()), currency="USD", full=True)["RAW"]

        for item in data:
            tmp = data[item]["USD"]
            price = float(tmp["PRICE"])
            total = price * assets[item]
            sym = await self.get_symbol_form_db(item, price, total)
            array.append(
                {
                    "symbol": item,
                    "amount": assets[item],
                    "total": total,
                    "img": domain + tmp["IMAGEURL"],
                }
            )

        availableMargin = await self.get_orders() or 0
        dictionary["total"] = pretify(totalMargin + availableMargin)
        dictionary["assets"] = array
        dictionary["available"] = pretify(totalMargin)

        await self.send_json(dictionary)
        await asyncio.sleep(1)

    async def disconnect(self, close_code):
        self.close()

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            while True:
                await asyncio.ensure_future(self.send_data())

    @database_sync_to_async
    def get_portfolio(self):
        return list(
            Portfolio.objects.all()
            .filter(
                usr_id=self.user.id,
                marketType="spot",
                amount__gt=0,
            )
            .order_by("-equivalentAmount")
        )

    @database_sync_to_async
    def get_orders(self):
        return (
            LimitOrders.objects.all()
            .filter(
                usr_id=self.user.id,
                amount__gt=0,
            )
            .aggregate(sum=Sum("equivalentAmount"))["sum"]
        )

    @database_sync_to_async
    def get_symbol_form_db(self, symbol, price, total):
        sym = Portfolio.objects.get(
            usr_id=self.user.id,
            marketType="spot",
            cryptoName=symbol,
        )
        LimitOrders.objects.filter(usr_id=self.user.id, pair__startswith=symbol, type="sell").update(
            equivalentAmount=F("amount_float") * price
        )
        sym.equivalentAmount = total
        sym.save()


class HistoriesConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        self.unicastName = f"{self.user}_HSTunicast"

        if self.user.is_authenticated:
            await (self.channel_layer.group_add)(self.unicastName, self.channel_name)
            await self.accept()
        else:
            await self.close()

    async def receive_json(self, content, **kwargs):
        page = content["page"]
        result = await self.initialFilling(page)
        await self.send_json(result)

    async def disconnect(self, code):
        pass

    async def send_data(self, event):
        data = event["content"]
        await self.send_json(data)

    @database_sync_to_async
    def initialFilling(self, page):

        before = (page - 1) * 10
        after = page * 10
        histObj = TradeHistory.objects.filter(usr_id=self.user.id).order_by("-id")[before:after]

        hist_content = dict()

        for index, item in enumerate(histObj):
            hist_content[str(index)] = {
                "header": "hist_responses",
                "type": item.type,
                "pair": item.pair,
                "pairPrice": item.pairPrice,
                "amount": item.amount,
                "date": item.time.strftime("%Y-%m-%d:%H:%M"),
                "price": item.price,
            }

        return hist_content


class OpenOrdersConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        self.unicastName = f"{self.user}_ORDRunicast"

        if self.user.is_authenticated:
            await (self.channel_layer.group_add)(self.unicastName, self.channel_name)
            await self.accept()
        else:
            await self.close()

    async def receive_json(self, content, **kwargs):
        if content.get("page"):
            page = content["page"]
            result = await self.initialFilling(page)
            await self.send_json(result)
        else:
            await self.cancelOrder(content.get("cancel"))

    async def disconnect(self, code):
        pass

    async def send_data(self, event):
        data = event["content"]
        await self.send_json(data)

    @database_sync_to_async
    def initialFilling(self, page):
        before = (page - 1) * 10
        after = page * 10
        orderObj = list(LimitOrders.objects.filter(usr_id=self.user.id).order_by("-id")[before:after])
        futuresObj = list(FuturesOrders.objects.filter(usr_id=self.user.id, complete=False))
        open_orders = []
        for item in orderObj:
            open_orders.append({
                "header": "order_responses",
                "type": item.type,
                "pair": item.pair,
                "pairPrice": item.pairPrice,
                "amount": item.amount,
                "id": item.id,
                "orderType": "limit",
                "complete": False,
                "pnl": None,
                "pnl_percent": None,
                "is_futures": False,
            })
        for fut in futuresObj:
            try:
                amount = float(fut.amount.split()[0]) if isinstance(fut.amount, str) else float(fut.amount)
            except Exception:
                amount = 0
            entry = fut.entryPrice
            leverage = fut.leverage
            market_price = fut.marketPrice
            pnl = 0
            pnl_percent = 0
            if entry and market_price and leverage and amount:
                if fut.type.lower() == "long":
                    pnl = (market_price - entry) * amount * leverage
                    pnl_percent = ((market_price - entry) / entry) * leverage * 100
                elif fut.type.lower() == "short":
                    pnl = (entry - market_price) * amount * leverage
                    pnl_percent = ((entry - market_price) / entry) * leverage * 100
            open_orders.append({
                "header": "order_responses",
                "type": fut.type,
                "pair": fut.pair,
                "pairPrice": fut.entryPrice,
                "amount": fut.amount,
                "id": f"futures-{fut.id}",
                "orderType": "futures",
                "complete": False,
                "pnl": round(pnl, 4),
                "pnl_percent": round(pnl_percent, 2),
                "is_futures": True,
                "leverage": fut.leverage,
                "marketPrice": fut.marketPrice,
            })
        return open_orders

    @database_sync_to_async
    def cancelOrder(self, ids):
        orders = LimitOrders.objects.filter(
            usr_id=self.user.id,
            pk__in=ids,
        )
        for order in orders:
            type_ = 1 if order.type == "buy" else 0
            p_price = order.pairPrice * order.amount_float if order.type == "buy" else order.amount_float
            Portfolio.objects.filter(usr_id=self.user.id, cryptoName=order.pair.split("-")[type_]).update(
                amount=F("amount") + p_price
            )
        orders.delete()
