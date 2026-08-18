from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import DATA_MODE
from app.mock_provider import MockProvider
from app.ifind_provider import IFindProvider
from app.strategy import build_wencai_query, matches

BASE = Path(__file__).resolve().parent
app = FastAPI(title="A股量化分析工作台", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
provider = IFindProvider() if DATA_MODE == "ifind" else MockProvider()


class ScreenRequest(BaseModel):
    exclude_st: bool = True
    min_amount: float = 3
    min_turnover: float = 3
    max_turnover: float = 12
    min_volume_ratio: float = 1.2
    min_change: float = -3
    max_change: float = 7
    min_main_inflow: float = 5000
    price_above_ma20: bool = True
    ma20_up: bool = True


@app.get("/")
async def home():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/health")
async def health():
    status = await provider.health()
    return {"ok": True, "data_mode": DATA_MODE, **status}


@app.get("/api/market/overview")
async def overview():
    try:
        return await provider.overview()
    except Exception as e:
        raise HTTPException(502, str(e))


@app.get("/api/market/funds")
async def funds():
    try:
        return {"industries": await provider.fund_industries(), "stocks": await provider.stocks()}
    except Exception as e:
        raise HTTPException(502, str(e))


@app.get("/api/stocks")
async def stocks():
    return await provider.stocks()


@app.get("/api/stock/{code}")
async def stock(code: str):
    item = await provider.stock_detail(code)
    if not item:
        raise HTTPException(404, "未找到股票")
    return item


@app.post("/api/screener")
async def screener(req: ScreenRequest):
    c = req.model_dump()
    query = build_wencai_query(c)
    if DATA_MODE == "ifind":
        raw = await provider.wencai(query)
        return {"mode":"ifind", "query":query, "raw":raw, "results":[]}
    rows = await provider.stocks()
    results = [s for s in rows if matches(s, c)]
    results.sort(key=lambda x: (x.get("score", 0), x.get("main_inflow", 0)), reverse=True)
    return {"mode":"demo", "query":query, "count":len(results), "results":results}


@app.get("/api/presets")
async def presets():
    return [
        {"name":"主力资金启动","desc":"资金流入 + 放量 + MA20上方","criteria":{"min_amount":3,"min_turnover":3,"max_turnover":12,"min_volume_ratio":1.2,"min_change":-3,"max_change":7,"min_main_inflow":5000,"price_above_ma20":True,"ma20_up":True,"exclude_st":True}},
        {"name":"强势放量突破","desc":"高量比、正涨幅、趋势向上","criteria":{"min_amount":5,"min_turnover":2,"max_turnover":15,"min_volume_ratio":1.6,"min_change":1,"max_change":8,"min_main_inflow":2000,"price_above_ma20":True,"ma20_up":True,"exclude_st":True}},
        {"name":"温和吸筹","desc":"限制涨幅，寻找资金流入但未明显拉升","criteria":{"min_amount":2,"min_turnover":1,"max_turnover":8,"min_volume_ratio":0.9,"min_change":-2,"max_change":3,"min_main_inflow":3000,"price_above_ma20":False,"ma20_up":False,"exclude_st":True}},
    ]
