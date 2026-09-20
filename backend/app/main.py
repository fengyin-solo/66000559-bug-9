import asyncio, time, random, math, json, threading
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Grid Trading Engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ACTIVE_CLIENTS = []
SIM_RUNNING = True
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
        for ws in ACTIVE_CLIENTS:
            try: asyncio.run_coroutine_threadsafe(ws.send_text(payload), asyncio.get_event_loop())
            except: pass
        time.sleep(0.5)


@app.on_event("startup")
async def startup():
    threading.Thread(target=simulate_market, daemon=True).start()


@app.post("/api/backtest")
def run_backtest(config: GridConfig):
    # ---- 参数校验：明确返回 400，而不是 500 白屏 ----
    if config.gridCount <= 0:
        return JSONResponse(status_code=400, content={"detail": "网格数量必须大于 0"})
    if config.lowerPrice <= 0 or config.upperPrice <= 0:
        return JSONResponse(status_code=400, content={"detail": "网格价格上下限必须大于 0"})
    if config.upperPrice <= config.lowerPrice:
        return JSONResponse(status_code=400, content={"detail": f"上限价格（{config.upperPrice}）必须大于下限价格（{config.lowerPrice}）"})
    if config.capitalPerGrid <= 0:
        return JSONResponse(status_code=400, content={"detail": "每格资金必须大于 0"})
    if config.initialCapital <= 0:
        return JSONResponse(status_code=400, content={"detail": "初始资金必须大于 0"})

    try:
        step = (config.upperPrice - config.lowerPrice) / config.gridCount
        grid_prices = [config.lowerPrice + i * step for i in range(config.gridCount + 1)]

        # 固定随机源，保证同一参数多次回测结果一致
        rng = random.Random(42)

        # Simulate prices
        prices = [100.0]
        for _ in range(200):
            prices.append(prices[-1] + rng.gauss(0, 1.2))
        prices = [max(70.0, min(140.0, p)) for p in prices]

        buy_grids = {}  # price -> {"qty": quantity} 已买入未平仓的网格
        orders = []
        cash = config.initialCapital
        holdings = 0.0
        equity_curve = [round(cash, 2)]
        order_id = 0

        for p in prices:
            for gp in grid_prices:
                # Buy signal
                if p <= gp and gp not in buy_grids and cash >= config.capitalPerGrid:
                    qty = config.capitalPerGrid / gp
                    cash -= config.capitalPerGrid
                    holdings += qty
                    buy_grids[gp] = {"qty": qty}
                    order_id += 1
                    orders.append({"id": order_id, "price": round(gp, 2), "side": "BUY", "quantity": round(qty, 2), "status": "FILLED", "profit": 0})

                # Sell signal
                upper_gp = gp + step * 0.5
                if p >= upper_gp and gp in buy_grids:
                    qty = buy_grids[gp]["qty"]
                    sell_price = upper_gp
                    profit = round(qty * (sell_price - gp), 2)  # 逐笔盈亏按两位小数入账
                    cash += config.capitalPerGrid + profit
                    holdings -= qty
                    del buy_grids[gp]
                    order_id += 1
                    orders.append({"id": order_id, "price": round(sell_price, 2), "side": "SELL", "quantity": round(qty, 2), "status": "FILLED", "profit": profit})

            equity = cash + holdings * p
            equity_curve.append(round(equity, 2))

        # ---- 期末按最后一个成交价强制平仓，使所有口径统一 ----
        # 总盈亏 = 全部 SELL（含期末平仓）逐笔盈亏之和 = 期末现金 - 初始资金
        final_price = prices[-1]
        for gp, pos in list(buy_grids.items()):
            qty = pos["qty"]
            profit = round(qty * (final_price - gp), 2)
            cash += config.capitalPerGrid + profit
            holdings -= qty
            order_id += 1
            orders.append({
                "id": order_id, "price": round(final_price, 2), "side": "SELL",
                "quantity": round(qty, 2), "status": "CLOSED", "profit": profit, "closing": True,
            })
        buy_grids.clear()

        sell_orders = [o for o in orders if o["side"] == "SELL"]
        total_profit = round(sum(o["profit"] for o in sell_orders), 2)
        # 平仓后全为现金，净值曲线末点与总盈亏严格对齐
        equity_curve.append(round(config.initialCapital + total_profit, 2))
        return_rate = round(total_profit / config.initialCapital * 100, 2)

        # Sharpe ratio（此前 list + float 会直接抛 TypeError 导致接口 500）
        eq_arr = np.array(equity_curve, dtype=float)
        eq_returns = np.diff(eq_arr) / (eq_arr[:-1] + 1e-9)
        sharpe = float(eq_returns.mean() / max(eq_returns.std(), 1e-9) * math.sqrt(252)) if len(eq_returns) > 1 else 0.0

        # Max drawdown
        peak = equity_curve[0]
        max_dd = 0.0
        for e in equity_curve:
            if e > peak: peak = e
            dd = (peak - e) / peak * 100
            max_dd = max(max_dd, dd)

        # Win rate：按平仓（SELL）笔数统计，与“成交笔数”同口径
        wins = sum(1 for o in sell_orders if o["profit"] > 0)
        win_rate = (wins / len(sell_orders) * 100) if sell_orders else 0.0

        return {
            "orders": orders,
            "totalProfit": total_profit,
            "returnRate": return_rate,
            "sharpeRatio": round(sharpe, 2),
            "maxDrawdown": round(max_dd, 2),
            "winRate": round(win_rate, 1),
            "equityCurve": equity_curve,
            "config": {
                "lowerPrice": config.lowerPrice,
                "upperPrice": config.upperPrice,
                "gridCount": config.gridCount,
                "capitalPerGrid": config.capitalPerGrid,
                "initialCapital": config.initialCapital,
            },
        }
    except Exception as exc:  # 任何计算异常都返回可读原因，前端不再无限转圈
        return JSONResponse(status_code=500, content={"detail": f"回测计算失败：{type(exc).__name__}: {exc}"})


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    ACTIVE_CLIENTS.append(ws)
    try:
        while True: await ws.receive_text()
    except:
        if ws in ACTIVE_CLIENTS: ACTIVE_CLIENTS.remove(ws)
