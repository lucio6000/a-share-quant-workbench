from __future__ import annotations

import time
from typing import Any
import httpx
from .config import IFIND_BASE_URL, IFIND_REFRESH_TOKEN, IFIND_WATCHLIST


class IFindError(RuntimeError):
    pass


class IFindProvider:
    mode = "ifind"

    def __init__(self):
        self.refresh_token = IFIND_REFRESH_TOKEN
        self._access_token = ""
        self._access_exp = 0.0
        self.client = httpx.AsyncClient(timeout=20.0)

    async def _token(self) -> str:
        if not self.refresh_token:
            raise IFindError("未配置 IFIND_REFRESH_TOKEN")
        if self._access_token and time.time() < self._access_exp:
            return self._access_token
        r = await self.client.post(
            f"{IFIND_BASE_URL}/get_access_token",
            headers={"Content-Type":"application/json", "refresh_token": self.refresh_token},
        )
        r.raise_for_status()
        data = r.json()
        token = (data.get("data") or {}).get("access_token")
        if not token:
            raise IFindError(f"获取 access_token 失败: {data}")
        self._access_token = token
        self._access_exp = time.time() + 7 * 24 * 3600 - 600
        return token

    async def _post(self, endpoint: str, payload: dict[str, Any]):
        token = await self._token()
        r = await self.client.post(
            f"{IFIND_BASE_URL}/{endpoint}", json=payload,
            headers={"Content-Type":"application/json", "access_token":token},
        )
        r.raise_for_status()
        data = r.json()
        if data.get("errorcode") not in (None, 0):
            raise IFindError(data.get("errmsg") or str(data))
        return data

    async def health(self):
        try:
            await self._token()
            return {"connected": True, "mode": "ifind", "message": "iFinD HTTP API 已连接"}
        except Exception as e:
            return {"connected": False, "mode": "ifind", "message": str(e)}

    @staticmethod
    def _tables_to_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
        tables = data.get("tables") or []
        rows: list[dict[str, Any]] = []
        for t in tables:
            code = t.get("thscode") or t.get("code") or ""
            table = t.get("table") or {}
            row = {"code": code}
            for k, v in table.items():
                row[k] = v[0] if isinstance(v, list) and v else v
            if row.get("code"):
                rows.append(row)
        return rows

    async def realtime(self, codes: list[str], indicators: str):
        return await self._post("real_time_quotation", {
            "codes": ",".join(codes), "indicators": indicators
        })

    async def overview(self):
        codes = ["000001.SH", "399001.SZ", "399006.SZ"]
        raw = await self.realtime(codes, "latest,changeRatio,amount")
        rows = self._tables_to_rows(raw)
        names = {"000001.SH":"上证指数","399001.SZ":"深证成指","399006.SZ":"创业板指"}
        indexes = []
        for r in rows:
            indexes.append({
                "name": names.get(r["code"], r["code"]), "code": r["code"],
                "value": r.get("latest"), "change": r.get("changeRatio")
            })
        return {
            "indexes": indexes, "up": None, "down": None, "limit_up": None, "limit_down": None,
            "turnover_amount": None, "sentiment": None, "updated_at": time.strftime("%H:%M:%S")
        }

    async def wencai(self, query: str):
        return await self._post("smart_stock_picking", {"searchstring": query, "searchtype":"stock"})

    async def stocks(self):
        raw = await self.realtime(IFIND_WATCHLIST, "latest,changeRatio,amount")
        rows = self._tables_to_rows(raw)
        out = []
        for r in rows:
            out.append({
                "code": r.get("code"), "name": r.get("code"), "industry":"—",
                "price": r.get("latest"), "change": r.get("changeRatio"),
                "amount": (float(r.get("amount") or 0) / 100000000),
                "turnover": None, "volume_ratio": None, "main_inflow": None,
                "main_inflow_rate": None, "ma20_gap": None, "ma20_up": None,
                "score": None, "reasons": ["真实行情已接入"],
                "risks": ["资金/换手等特色指标需按你的iFinD权限在超级命令确认指标代码后映射"]
            })
        return out

    async def fund_industries(self):
        raw = await self.wencai("今日行业主力资金净流入排名")
        return [{"raw": raw, "industry":"问财原始结果", "main_inflow":0, "amount":0, "up_ratio":0}]

    async def stock_detail(self, code: str):
        raw = await self.realtime([code], "latest,changeRatio,amount,open,high,low")
        rows = self._tables_to_rows(raw)
        if not rows:
            return None
        r = rows[0]
        return {
            "code": code, "name": code, "industry":"—", "price":r.get("latest"),
            "change":r.get("changeRatio"), "amount":float(r.get("amount") or 0)/100000000,
            "turnover":None, "volume_ratio":None, "main_inflow":None, "main_inflow_rate":None,
            "ma20_gap":None, "ma20_up":None, "score":None,
            "reasons":[f"开 {r.get('open')} / 高 {r.get('high')} / 低 {r.get('low')}", "iFinD实时行情"],
            "risks":[], "fund_timeline":[]
        }
