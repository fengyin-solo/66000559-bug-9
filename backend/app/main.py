import asyncio, time, random, math, json, threading
from typing import Optional
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Grid Trading Engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ACTIVE_CLIENTS = []
SIM_RUNNING = True
MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None
current_price = 100.0
ticks_history = []

class GridConfig(BaseModel):
    lowerPrice: float = 95
    upperPrice: float = 115
    gridCount: int = 20
    capitalPerGrid: float = 1000
    initialCapital: float = 100000


def simulate_market():
    global current_price, ticks_history
    price = 100.0
    while SIM_RUNNING:
        drift = 0.005 * math.sin(time.time() * 0.05)
        price += random.gauss(drift, 0.3)
        price = max(80, min(130, price))
        current_price = price
        tick = {
            "time": time.strftime("%H:%M:%S"),
            "price": round(price, 2),
            "bid": round(price - random.uniform(0.01, 0.05), 2),
            "ask": round(price + random.uniform(0.01, 0.05), 2),
            "volume": random.randint(100, 5000)
        }
        ticks_history.append(tick)
        if len(ticks_history) > 200:
            ticks_history = ticks_history[-200:]

        # Order book
        bids = [[round(price - 0.01 * i, 2), random.randint(100, 1000)] for i in range(1, 11)]
        asks = [[round(price + 0.01 * i, 2), random.randint(100, 1000)] for i in range(1, 11)]
        order_book = {"bids": bids, "asks": asks, "midPrice": price, "spread": round(asks[0][0] - bids[0][0], 2)}

        payload = json.dumps({"ticks": ticks_history[-60:], "orderBook": order_book})
        if MAIN_LOOP is not None:
            for ws in ACTIVE_CLIENTS:
                try: asyncio.run_coroutine_threadsafe(ws.send_text(payload), MAIN_LOOP)
                except: pass
        time.sleep(0.5)


@app.on_event("startup")
async def startup():
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_event_loop()
    threading.Thread(target=simulate_market, daemon=True).start()


@app.post("/api/backtest")
def run_backtest(config: GridConfig):
    # ---- 参数校验：失败时返回明确原因，而不是 500 ----
    if config.gridCount <= 0:
        raise HTTPException(status_code=422, detail="网格数量必须大于 0")
    if config.lowerPrice <= 0 or config.upperPrice <= 0:
        raise HTTPException(status_code=422, detail="网格价格必须大于 0")
    if config.lowerPrice >= config.upperPrice:
        raise HTTPException(status_code=422, detail="下限价格必须小于上限价格")
    if config.capitalPerGrid <= 0:
        raise HTTPException(status_code=422, detail="每格资金必须大于 0")
    if config.initialCapital <= 0:
        raise HTTPException(status_code=422, detail="初始资金必须大于 0")

    step = (config.upperPrice - config.lowerPrice) / config.gridCount
    grid_prices = [config.lowerPrice + i * step for i in range(config.gridCount + 1)]

    # ---- 确定性行情：同参数结果一致，便于刷新后核对 ----
    rng = np.random.default_rng(42)
    prices = [100.0]
    for _ in range(200):
        prices.append(prices[-1] + float(rng.normal(0, 1.2)))
    prices = [max(70.0, min(140.0, p)) for p in prices]

    # open_grids: 网格价 -> 该格买入数量（同一份数量用于卖出，避免份额对不上）
    open_grids = {}
    orders = []
    cash = config.initialCapital
    holdings = 0.0
    equity_curve = [round(cash, 2)]
    order_id = 0

    def buy(gp, qty, cost):
        nonlocal cash, holdings
        cash = round(cash - cost, 2)
        holdings += qty
        open_grids[gp] = qty

    def sell(gp, qty, price):
        nonlocal cash, holdings
        # 成本、收入、盈亏都按同一份已舍入数量记账；
        # 卖出加回全额收入，逐笔(收入-成本)之和与现金账严格闭合
        cost = round(qty * gp, 2)
        proceeds = round(qty * price, 2)
        profit = round(proceeds - cost, 2)
        cash = round(cash + proceeds, 2)
        holdings -= qty
        open_grids.pop(gp, None)
        return profit

    for p in prices:
        for gp in grid_prices:
            # Buy signal：在网格价成交，现金与持仓都按同一份（已舍入）数量记账
            qty = round(config.capitalPerGrid / gp, 4)
            cost = round(qty * gp, 2)
            if p <= gp and gp not in open_grids and cash >= cost:
                buy(gp, qty, cost)
                order_id += 1
                orders.append({"id": order_id, "price": round(gp, 2), "side": "BUY", "quantity": qty, "status": "FILLED", "profit": 0})

            # Sell signal（同一网格格的上半档）
            upper_gp = gp + step * 0.5
            if p >= upper_gp and gp in open_grids:
                sell_price = round(upper_gp, 2)
                open_qty = open_grids[gp]
                profit = sell(gp, open_qty, upper_gp)
                order_id += 1
                orders.append({"id": order_id, "price": sell_price, "side": "SELL", "quantity": open_qty, "status": "FILLED", "profit": profit})

        equity = cash + holdings * p
        equity_curve.append(round(equity, 2))

    # ---- 期末按最后价强制平仓：未实现盈亏全部落成逐笔 SELL，
    #      使「指标区总盈亏」==「明细逐笔盈亏汇总」==「资金曲线终点 − 初始资金」 ----
    last_price = prices[-1]
    for gp in list(open_grids.keys()):
        open_qty = open_grids[gp]
        profit = sell(gp, open_qty, last_price)
        order_id += 1
        orders.append({"id": order_id, "price": round(last_price, 2), "side": "SELL", "quantity": open_qty, "status": "FILLED", "profit": profit})

    total_profit = round(cash - config.initialCapital, 2)
    equity_curve.append(round(cash, 2))  # 平仓后全部为现金，终点与总盈亏对齐
    return_rate = round((total_profit / config.initialCapital) * 100, 2)

    # Sharpe ratio
    eq_returns = np.diff(equity_curve) / (np.array(equity_curve[:-1]) + 1e-5)
    sharpe = float(np.mean(eq_returns) / max(np.std(eq_returns), 1e-5) * np.sqrt(252)) if len(eq_returns) > 1 else 0

    # Max drawdown
    peak = equity_curve[0]
    max_dd = 0.0
    for e in equity_curve:
        if e > peak: peak = e
        dd = (peak - e) / peak * 100
        max_dd = max(max_dd, dd)

    # Win rate（全部已平仓，SELL 即完整交易对）
    sell_orders = [o for o in orders if o["side"] == "SELL"]
    wins = sum(1 for o in sell_orders if o["profit"] > 0)
    win_rate = (wins / len(sell_orders) * 100) if sell_orders else 0

    return {
        "orders": orders,
        "totalProfit": total_profit,
        "returnRate": return_rate,
        "sharpeRatio": round(sharpe, 2),
        "maxDrawdown": round(max_dd, 2),
        "winRate": round(win_rate, 1),
        "equityCurve": equity_curve
    }


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    ACTIVE_CLIENTS.append(ws)
    try:
        while True: await ws.receive_text()
    except: 
        if ws in ACTIVE_CLIENTS: ACTIVE_CLIENTS.remove(ws)