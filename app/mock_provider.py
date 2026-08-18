from __future__ import annotations

import math
import random
from datetime import datetime
from .strategy import score_stock

BASE = [
    ("300750.SZ", "宁德时代", "电力设备"), ("600519.SH", "贵州茅台", "食品饮料"),
    ("000858.SZ", "五粮液", "食品饮料"), ("601318.SH", "中国平安", "非银金融"),
    ("300033.SZ", "同花顺", "计算机"), ("002475.SZ", "立讯精密", "电子"),
    ("000333.SZ", "美的集团", "家用电器"), ("600036.SH", "招商银行", "银行"),
    ("601012.SH", "隆基绿能", "电力设备"), ("002594.SZ", "比亚迪", "汽车"),
    ("600276.SH", "恒瑞医药", "医药生物"), ("300059.SZ", "东方财富", "非银金融"),
    ("601888.SH", "中国中免", "商贸零售"), ("000001.SZ", "平安银行", "银行"),
    ("600900.SH", "长江电力", "公用事业"), ("601899.SH", "紫金矿业", "有色金属"),
    ("002230.SZ", "科大讯飞", "计算机"), ("000725.SZ", "京东方A", "电子"),
    ("601138.SH", "工业富联", "电子"), ("603986.SH", "兆易创新", "电子"),
    ("688981.SH", "中芯国际", "电子"), ("300124.SZ", "汇川技术", "机械设备"),
    ("600030.SH", "中信证券", "非银金融"), ("601668.SH", "中国建筑", "建筑装饰"),
    ("600887.SH", "伊利股份", "食品饮料"), ("002714.SZ", "牧原股份", "农林牧渔"),
    ("300308.SZ", "中际旭创", "通信"), ("300502.SZ", "新易盛", "通信"),
    ("002371.SZ", "北方华创", "电子"), ("688041.SH", "海光信息", "电子"),
]


def _rng():
    bucket = int(datetime.now().timestamp() // 15)
    return random.Random(bucket)


def _stocks():
    rng = _rng()
    rows = []
    for idx, (code, name, industry) in enumerate(BASE):
        change = round(rng.uniform(-4.5, 8.8) + math.sin(idx) * 1.2, 2)
        amount = round(rng.uniform(2.0, 85.0), 2)
        turnover = round(rng.uniform(0.8, 16.5), 2)
        vr = round(rng.uniform(0.55, 2.8), 2)
        inflow = round(rng.uniform(-16000, 26000), 0)
        inflow_rate = round(inflow / max(amount * 10000, 1) * 100, 2)
        ma20_gap = round(rng.uniform(-6, 9), 2)
        price = round(rng.uniform(6, 360), 2)
        row = {
            "code": code, "name": name, "industry": industry, "price": price,
            "change": change, "amount": amount, "turnover": turnover,
            "volume_ratio": vr, "main_inflow": inflow, "main_inflow_rate": inflow_rate,
            "ma20_gap": ma20_gap, "ma20_up": rng.random() > 0.36,
        }
        score, reasons, risks = score_stock(row)
        row.update(score=score, reasons=reasons, risks=risks)
        rows.append(row)
    return rows


class MockProvider:
    mode = "demo"

    async def health(self):
        return {"connected": True, "mode": "demo", "message": "演示数据模式"}

    async def overview(self):
        rng = _rng()
        return {
            "indexes": [
                {"name":"上证指数","code":"000001.SH","value":round(3600+rng.uniform(-30,40),2),"change":round(rng.uniform(-1.2,1.6),2)},
                {"name":"深证成指","code":"399001.SZ","value":round(11200+rng.uniform(-120,160),2),"change":round(rng.uniform(-1.4,1.9),2)},
                {"name":"创业板指","code":"399006.SZ","value":round(2320+rng.uniform(-35,45),2),"change":round(rng.uniform(-1.8,2.3),2)},
            ],
            "up": rng.randint(2600, 3900), "down": rng.randint(1100, 2300),
            "limit_up": rng.randint(45, 92), "limit_down": rng.randint(3, 22),
            "turnover_amount": round(rng.uniform(1.35, 2.15), 2),
            "sentiment": rng.randint(58, 86),
            "updated_at": datetime.now().strftime("%H:%M:%S"),
        }

    async def stocks(self):
        return _stocks()

    async def fund_industries(self):
        rows = _stocks()
        agg = {}
        for s in rows:
            x = agg.setdefault(s["industry"], {"industry":s["industry"],"main_inflow":0,"amount":0,"up":0,"count":0})
            x["main_inflow"] += s["main_inflow"]
            x["amount"] += s["amount"]
            x["count"] += 1
            x["up"] += 1 if s["change"] > 0 else 0
        out = []
        for x in agg.values():
            x["main_inflow"] = round(x["main_inflow"], 0)
            x["amount"] = round(x["amount"], 2)
            x["up_ratio"] = round(x["up"] / x["count"] * 100, 1)
            out.append(x)
        return sorted(out, key=lambda x: x["main_inflow"], reverse=True)

    async def stock_detail(self, code: str):
        for s in _stocks():
            if s["code"].upper() == code.upper():
                rng = _rng()
                s["fund_timeline"] = [
                    {"time":t, "value":round(s["main_inflow"] * f + rng.uniform(-900,900), 0)}
                    for t, f in [("10:00",.22),("10:30",.42),("11:00",.55),("13:30",.66),("14:00",.82),("当前",1)]
                ]
                return s
        return None
