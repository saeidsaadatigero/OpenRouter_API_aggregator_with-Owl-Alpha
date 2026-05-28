
from sortedcontainers import SortedDict
from typing import Optional, Tuple, List
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from decimal import Decimal


class Side(Enum):
    BID = "bid"
    ASK = "ask"


@dataclass
class Order:
    order_id: str
    price: Decimal
    quantity: Decimal
    side: Side
    timestamp: float


@dataclass
class PriceLevel:
    price: Decimal
    quantity: Decimal
    orders: SortedDict = field(default_factory=SortedDict)  # order_id -> Order

    def add_order(self, order: Order):
        self.orders[order.order_id] = order
        self.quantity += order.quantity

    def remove_order(self, order_id: str) -> Optional[Order]:
        order = self.orders.pop(order_id, None)
        if order:
            self.quantity -= order.quantity
            return order
        return None

    def __bool__(self):
        return bool(self.orders)


class OrderBook:
    def __init__(self):
        self.bids: SortedDict[Decimal, PriceLevel] = SortedDict()
        self.asks: SortedDict[Decimal, PriceLevel] = SortedDict()
        self.orders: Dict[str, Tuple[Side, Decimal] = {}  # order_id -> (side, price)
        self._lock = asyncio.Lock()

    async def add_order(self, order: Order) -> List[Tuple[Decimal, Decimal, Decimal]:
        async with self._lock:
            trades = []
            if order.side == Side.BID:
                trades = await self._match_bid(order)
            else:
                trades = await self._match_ask(order)

            if order.quantity > 0:
                book = self.bids if order.side == Side.BID else self.asks
                if order.price not in book:
                    book[order.price] = PriceLevel(price=order.price, quantity=Decimal("0"))
                book[order.price].add_order(order)
                self.orders[order.order_id] = (order.side, order.price)

            return trades

    async def _match_bid(self, order: Order) -> List[Tuple[Decimal, Decimal, Decimal]:
        trades = []
        while order.quantity > 0 and self.asks and self.asks.peekitem(0)[0] <= order.price:
            best_ask_price, best_ask_level = self.asks.peekitem(0)
            for ask_order_id, ask_order in list(best_ask_level.orders.items()):
                fill_qty = min(order.quantity, ask_order.quantity)
                trades.append((best_ask_price, fill_qty, ask_order.timestamp)
                order.quantity -= fill_qty
                ask_order.quantity -= fill_qty
                best_ask_level.quantity -= fill_qty
                if ask_order.quantity == 0:
                    best_ask_level.remove_order(ask_order_id)
                    del self.orders[ask_order_id]
                if best_ask_level.quantity == 0:
                    del self.asks[best_ask_price]
                if order.quantity == 0:
                    break
        return trades

    async def _match_ask(self, order: Order) -> List[Tuple[Decimal, Decimal, Decimal]:
        trades = []
        while order.quantity > 0 and self.bids and self.bids.peekitem(-1)[0] >= order.price:
            best_bid_price, best_bid_level = self.bids.peekitem(-1)
            for bid_order_id, bid_order in list(best_bid_level.orders.items()):
                fill_qty = min(order.quantity, bid_order.quantity)
                trades.append((best_bid_price, fill_qty, bid_order.timestamp)
                order.quantity -= fill_qty
                bid_order.quantity -= fill_qty
                best_bid_level.quantity -= fill_qty
                if bid_order.quantity == 0:
                    best_bid_level.remove_order(bid_order_id)
                    del self.orders[bid_order_id]
                if best_bid_level.quantity == 0:
                    del self.bids[best_bid_price]
                if order.quantity == 0:
                    break
        return trades

    async def cancel_order(self, order_id: str) -> bool:
        async with self._lock:
            if order_id not in self.orders:
                return False
            side, price = self.orders.pop(order_id)
            book = self.bids if side == Side.BID else self.asks
            if price in book:
                level = book[price]
                level.remove_order(order_id)
                if not level:
                    del book[price]
                return True
            return False

    async def get_best_bid(self) -> Optional[Tuple[Decimal, Decimal]:
        async with self._lock:
            if self.bids:
                price, level = self.bids.peekitem(-1)
                return (price, level.quantity)
            return None

    async def get_best_ask(self) -> Optional[Tuple[Decimal, Decimal]:
        async with self._lock:
            if self.asks:
                price, level = self.asks.peekitem(0)
                return (price, level.quantity)
            return None

    async def get_depth(self, levels: int = 10) -> Tuple[List[Tuple[Decimal, Decimal], List[Tuple[Decimal, Decimal]]:
        async with self._lock:
            bids = []
            asks = []
            for i, (price, level) in enumerate(reversed(self.bids.items())):
                if i >= levels:
                    break
                if level.quantity > 0:
                    bids.append((price, level.quantity))
            for i, (price, level) in enumerate(self.asks.items()):
                if i >= levels:
                    break
                if level.quantity > 0:
                    asks.append((price, level.quantity))
            return bids, asks
