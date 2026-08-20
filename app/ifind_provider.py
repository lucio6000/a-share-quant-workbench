from __future__ import annotations

import re
import time
from typing import Any

import httpx

from .config import IFIND_BASE_URL, IFIND_REFRESH_TOKEN, IFIND_WATCHLIST
from .strategy import score_stock


class IFindError(RuntimeError):
    pass


class IFindProvider:
    mode = "ifind"

    def __init__(self):
        self.refresh_token = IFIND_REFRESH_TOKEN
        self._access_token = ""
        self._access_exp = 0.0
        self.client = httpx.AsyncClient(timeout=30.0)
        self._cache: dict[str, tuple[float, Any]] = {}

    async def _token(self) -> str:
        if not self.refresh_token:
            raise IFindError("未配置 IFIND_REFRESH_TOKEN")
        if self._access_token and time.time() < self._access_exp:
            return self._access_token
        r = await self.client.post(
            f"{IFIND_BASE_URL}/get_access_token",
            headers={"Content-Type": "application/json", "refresh_token": self.refresh_token},
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
            f"{IFIND_BASE_URL}/{endpoint}",
            json=payload,
            headers={"Content-Type": "application/json", "access_token": token, "ifindlang": "cn"},
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
    def _table_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        tables = data.get("tables") or []
        if isinstance(tables, dict):
            tables = [tables]
        for t in tables:
            if not isinstance(t, dict):
                continue
            table = t.get("table") or {}
            if not isinstance(table, dict):
                continue
            code_value = t.get("thscode") or t.get("code")
            lengths = [len(v) for v in table.values() if isinstance(v, list)]
            if isinstance(code_value, list):
                lengths.append(len(code_value))
            n = max(lengths or [1])
            for i in range(n):
                row: dict[str, Any] = {}
                if isinstance(code_value, list):
                    row["code"] = code_value[i] if i < len(code_value) else None
                elif code_value:
                    row["code"] = code_value
                for k, v in table.items():
                    row[k] = v[i] if isinstance(v, list) and i < len(v) else (v if not isinstance(v, list) else None)
                if row:
                    rows.append(row)
        return rows

    @classmethod
    def rows_from_response(cls, data: dict[str, Any]) -> list[dict[str, Any]]:
        rows = cls._table_rows(data)
        if rows:
            return rows
        payload = data.get("data")
        if isinstance(payload, list) and all(isinstance(x, dict) for x in payload):
            return payload
        if isinstance(payload, dict):
            if "tables" in payload:
                nested = cls._table_rows(payload)
                if nested:
                    return nested
            list_lengths = [len(v) for v in payload.values() if isinstance(v, list)]
            if list_lengths:
                n = max(list_lengths)
                out = []
                for i in range(n):
                    row = {}
                    for k, v in payload.items():
                        row[k] = v[i] if isinstance(v, list) and i < len(v) else (v if not isinstance(v, list) else None)
                    out.append(row)
                return out
        return []

    async def realtime(self, codes: list[str], indicators: str):
        if not codes:
            return {"tables": []}
        return await self._post("real_time_quotation", {
            "codes": ",".join(codes),
            "indicators": indicators,
        })

    async def overview(self):
        codes = ["000001.SH", "399001.SZ", "399006.SZ"]
        raw = await self.realtime(codes, "latest,changeRatio,amount")
        rows = self.rows_from_response(raw)
        names = {"000001.SH": "上证指数", "399001.SZ": "深证成指", "399006.SZ": "创业板指"}
        indexes = []
        for r in rows:
            code = str(r.get("code") or r.get("thscode") or "")
            indexes.append({
                "name": names.get(code, code),
                "code": code,
                "value": r.get("latest"),
                "change": r.get("changeRatio"),
            })
        return {
            "indexes": indexes,
            "up": None,
            "down": None,
            "limit_up": None,
            "limit_down": None,
            "turnover_amount": None,
            "sentiment": None,
            "updated_at": time.strftime("%H:%M:%S"),
        }

    async def wencai(self, query: str):
        return await self._post("smart_stock_picking", {
            "searchstring": query,
            "searchtype": "stock",
        })

    @staticmethod
    def _pick(row: dict[str, Any], *needles: str):
        for k, v in row.items():
            key = str(k).lower().replace(" ", "")
            if all(n.lower() in key for n in needles):
                return v
        return None

    @staticmethod
    def _num(value: Any, target: str = "plain") -> float | None:
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).replace(",", "").strip()
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if not m:
            return None
        n = float(m.group())
        if target == "yi":
            if "万亿" in s:
                n *= 10000
            elif "亿" in s:
                pass
            elif "万" in s:
                n /= 10000
            else:
                n /= 100000000
        elif target == "wan":
            if "万亿" in s:
                n *= 100000000
            elif "亿" in s:
                n *= 10000
            elif "万" in s:
                pass
            else:
                n /= 10000
        return n

    @classmethod
    def normalize_stock_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        code = row.get("code") or row.get("thscode") or row.get("THSCODE") or cls._pick(row, "股票代码") or cls._pick(row, "证券代码")
        name = cls._pick(row, "股票简称") or cls._pick(row, "证券简称") or cls._pick(row, "股票名称") or row.get("name") or code
        industry = cls._pick(row, "同花顺行业") or cls._pick(row, "所属行业") or cls._pick(row, "行业") or "—"
        price = row.get("latest") if row.get("latest") is not None else cls._pick(row, "最新价")
        change = row.get("changeRatio") if row.get("changeRatio") is not None else cls._pick(row, "涨跌幅")
        amount = row.get("amount") if row.get("amount") is not None else cls._pick(row, "成交额")
        turnover = cls._pick(row, "换手率")
        volume_ratio = cls._pick(row, "量比")
        main_inflow = cls._pick(row, "主力", "净流入") or cls._pick(row, "主力资金", "流入")
        main_inflow_rate = cls._pick(row, "主力", "净流入率")
        if isinstance(main_inflow, str) and "%" in main_inflow:
            main_inflow = None
        out = {
            "code": str(code or ""),
            "name": str(name or code or ""),
            "industry": str(industry or "—"),
            "price": cls._num(price),
            "change": cls._num(change),
            "amount": cls._num(amount, "yi"),
            "turnover": cls._num(turnover),
            "volume_ratio": cls._num(volume_ratio),
            "main_inflow": cls._num(main_inflow, "wan"),
            "main_inflow_rate": cls._num(main_inflow_rate),
            "ma20_gap": None,
            "ma20_up": None,
            "score": None,
            "reasons": ["iFinD / 问财真实数据"],
            "risks": [],
        }
        score, reasons, risks = score_stock(out)
        out["score"] = score
        out["reasons"] = reasons or out["reasons"]
        out["risks"] = risks
        return out

    async def wencai_stocks(self, query: str) -> list[dict[str, Any]]:
        raw = await self.wencai(query)
        rows = self.rows_from_response(raw)
        return [self.normalize_stock_row(r) for r in rows if isinstance(r, dict)]

    async def stocks(self):
        cache_key = "stocks"
        cached = self._cache.get(cache_key)
        if cached and time.time() - cached[0] < 20:
            return cached[1]
        try:
            query = "A股，非ST，最新价，今日涨跌幅，今日成交额，今日换手率，今日量比，今日主力净流入，所属同花顺行业"
            rows = await self.wencai_stocks(query)
            rows = [r for r in rows if r.get("code")]
            if rows:
                rows.sort(key=lambda x: (x.get("main_inflow") or 0, x.get("amount") or 0), reverse=True)
                result = rows[:300]
                self._cache[cache_key] = (time.time(), result)
                return result
        except Exception:
            pass
        raw = await self.realtime(IFIND_WATCHLIST, "latest,changeRatio,amount")
        rows = self.rows_from_response(raw)
        result = []
        for r in rows:
            item = self.normalize_stock_row(r)
            item["reasons"] = ["iFinD 实时行情；问财字段暂未返回"]
            result.append(item)
        self._cache[cache_key] = (time.time(), result)
        return result

    async def fund_industries(self):
        try:
            rows = await self.wencai_stocks("A股，非ST，今日主力净流入前200名，今日主力净流入，所属同花顺行业")
            agg: dict[str, dict[str, float]] = {}
            for r in rows:
                industry = r.get("industry") or "未分类"
                if industry == "—":
                    continue
                bucket = agg.setdefault(industry, {"main_inflow": 0.0, "count": 0.0})
                bucket["main_inflow"] += float(r.get("main_inflow") or 0)
                bucket["count"] += 1
            result = [{"industry": k, "main_inflow": v["main_inflow"], "amount": 0, "up_ratio": 0} for k, v in agg.items()]
            result.sort(key=lambda x: x["main_inflow"], reverse=True)
            return result[:20]
        except Exception:
            return []

    async def stock_detail(self, code: str):
        raw = await self.realtime([code], "latest,changeRatio,amount,open,high,low")
        rows = self.rows_from_response(raw)
        if not rows:
            return None
        r = rows[0]
        item = self.normalize_stock_row(r)
        item.update({
            "code": code,
            "reasons": [f"开 {r.get('open')} / 高 {r.get('high')} / 低 {r.get('low')}", "iFinD 实时行情"],
            "fund_timeline": [],
        })
        try:
            extra = await self.wencai_stocks(f"{code}，最新价，今日涨跌幅，今日成交额，今日换手率，今日量比，今日主力净流入，所属同花顺行业")
            if extra:
                merged = extra[0]
                merged["reasons"] = item["reasons"] + ["问财扩展字段"]
                merged["fund_timeline"] = []
                return merged
        except Exception:
            pass
        return item

    async def diagnose(self):
        realtime_raw = await self.realtime(["300033.SZ"], "latest,changeRatio,amount")
        diag: dict[str, Any] = {
            "mode": "ifind",
            "realtime_errorcode": realtime_raw.get("errorcode"),
            "realtime_table_count": len(realtime_raw.get("tables") or []),
            "realtime_rows": self.rows_from_response(realtime_raw)[:2],
        }
        try:
            wc_raw = await self.wencai("300033.SZ，最新价，今日涨跌幅，今日成交额，今日换手率，今日量比")
            diag.update({
                "wencai_errorcode": wc_raw.get("errorcode"),
                "wencai_top_keys": list(wc_raw.keys()),
                "wencai_table_count": len(wc_raw.get("tables") or []),
                "wencai_rows_preview": self.rows_from_response(wc_raw)[:2],
                "wencai_errmsg": wc_raw.get("errmsg"),
            })
        except Exception as e:
            diag["wencai_error"] = str(e)
        return diag
