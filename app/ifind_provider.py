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
        self._optional_errors: dict[str, str] = {}

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
            headers={
                "Content-Type": "application/json",
                "access_token": token,
                "ifindlang": "cn",
            },
        )
        r.raise_for_status()
        data = r.json()
        if data.get("errorcode") not in (None, 0):
            raise IFindError(data.get("errmsg") or str(data))
        if data.get("errmsg") and str(data.get("errmsg")).strip().lower() == "no data.":
            raise IFindError("no data.")
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
        return await self._post(
            "real_time_quotation",
            {"codes": ",".join(codes), "indicators": indicators},
        )

    async def wencai(self, query: str):
        return await self._post(
            "smart_stock_picking",
            {"searchstring": query, "searchtype": "stock"},
        )

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
            n = float(value)
            raw = ""
        else:
            raw = str(value).replace(",", "").strip()
            m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw)
            if not m:
                return None
            try:
                n = float(m.group())
            except ValueError:
                return None

        if target == "yi":
            if "万亿" in raw:
                n *= 10000
            elif "亿" in raw:
                pass
            elif "万" in raw:
                n /= 10000
            else:
                n /= 100000000
        elif target == "wan":
            if "万亿" in raw:
                n *= 100000000
            elif "亿" in raw:
                n *= 10000
            elif "万" in raw:
                pass
            else:
                n /= 10000
        return n

    @classmethod
    def normalize_stock_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        code = (
            row.get("code")
            or row.get("thscode")
            or row.get("THSCODE")
            or cls._pick(row, "股票代码")
            or cls._pick(row, "证券代码")
        )
        name = (
            cls._pick(row, "股票简称")
            or cls._pick(row, "证券简称")
            or cls._pick(row, "股票名称")
            or row.get("name")
            or code
        )
        industry = (
            cls._pick(row, "同花顺行业")
            or cls._pick(row, "所属行业")
            or cls._pick(row, "行业")
            or "—"
        )

        price = row.get("latest")
        if price is None:
            price = cls._pick(row, "最新价") or cls._pick(row, "收盘价") or cls._pick(row, "现价")

        change = row.get("changeRatio") if row.get("changeRatio") is not None else cls._pick(row, "涨跌幅")
        amount = row.get("amount") if row.get("amount") is not None else cls._pick(row, "成交额")
        turnover = cls._pick(row, "换手率")
        volume_ratio = cls._pick(row, "量比")
        main_inflow_rate = cls._pick(row, "主力", "净流入率")
        main_inflow = cls._pick(row, "主力", "净流入") or cls._pick(row, "主力资金", "流入")
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

    async def _cached_wencai(self, cache_key: str, queries: list[str], ttl: int = 900) -> list[dict[str, Any]]:
        cached = self._cache.get(cache_key)
        if cached and time.time() - cached[0] < ttl:
            return cached[1]

        last_error = ""
        for query in queries:
            try:
                rows = await self.wencai_stocks(query)
                rows = [r for r in rows if r.get("code")]
                if rows:
                    self._cache[cache_key] = (time.time(), rows)
                    self._optional_errors.pop(cache_key, None)
                    return rows
            except Exception as e:
                last_error = str(e)

        self._optional_errors[cache_key] = last_error or "no data."
        self._cache[cache_key] = (time.time(), [])
        return []

    async def _market_snapshot(self) -> list[dict[str, Any]]:
        # 基础快照必须只包含已验证可返回的普通行情字段。
        return await self._cached_wencai(
            "market_snapshot_base",
            [
                "A股，股票代码，股票简称，收盘价，今日涨跌幅，今日成交额，今日换手率，今日量比",
                "A股，收盘价，今日涨跌幅，今日成交额，今日换手率，今日量比",
            ],
            ttl=300,
        )

    async def _industry_rows(self) -> list[dict[str, Any]]:
        return await self._cached_wencai(
            "market_industry",
            [
                "A股，股票代码，股票简称，所属同花顺行业",
                "A股，股票代码，股票简称，同花顺行业",
                "A股，所属行业",
            ],
            ttl=1800,
        )

    async def _main_inflow_rows(self) -> list[dict[str, Any]]:
        return await self._cached_wencai(
            "market_main_inflow",
            [
                "A股，股票代码，股票简称，今日主力净流入",
                "A股，今日主力净流入",
            ],
            ttl=900,
        )

    async def _main_inflow_rate_rows(self) -> list[dict[str, Any]]:
        return await self._cached_wencai(
            "market_main_inflow_rate",
            [
                "A股，股票代码，股票简称，今日主力净流入率",
                "A股，今日主力净流入率",
            ],
            ttl=900,
        )

    @staticmethod
    def _merge_rows(base: list[dict[str, Any]], extras: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
        merged = {str(r.get("code")): dict(r) for r in base if r.get("code")}
        for rows in extras:
            for r in rows:
                code = str(r.get("code") or "")
                if not code or code not in merged:
                    continue
                target = merged[code]
                if r.get("industry") not in (None, "", "—"):
                    target["industry"] = r.get("industry")
                if r.get("main_inflow") is not None:
                    target["main_inflow"] = r.get("main_inflow")
                if r.get("main_inflow_rate") is not None:
                    target["main_inflow_rate"] = r.get("main_inflow_rate")
        result = list(merged.values())
        for item in result:
            score, reasons, risks = score_stock(item)
            item["score"] = score
            if reasons:
                item["reasons"] = reasons
            item["risks"] = risks
        return result

    async def _market_enriched(self) -> list[dict[str, Any]]:
        base = await self._market_snapshot()
        if not base:
            return []
        industry = await self._industry_rows()
        inflow = await self._main_inflow_rows()
        inflow_rate = await self._main_inflow_rate_rows()
        return self._merge_rows(base, [industry, inflow, inflow_rate])

    @staticmethod
    def _limit_threshold(code: str, name: str) -> float:
        # 粗略按板块规则判断涨跌停，用于首页统计。ST 单独按 5% 处理。
        upper_name = str(name or "").upper()
        if "ST" in upper_name:
            return 4.8
        if code.startswith(("300", "301", "688")):
            return 19.5
        if code.startswith(("4", "8", "92")):
            return 29.5
        return 9.5

    async def overview(self):
        codes = ["000001.SH", "399001.SZ", "399006.SZ"]
        raw = await self.realtime(codes, "latest,changeRatio,amount")
        rows = self.rows_from_response(raw)
        names = {
            "000001.SH": "上证指数",
            "399001.SZ": "深证成指",
            "399006.SZ": "创业板指",
        }
        indexes = []
        for r in rows:
            code = str(r.get("code") or r.get("thscode") or "")
            indexes.append(
                {
                    "name": names.get(code, code),
                    "code": code,
                    "value": r.get("latest"),
                    "change": r.get("changeRatio"),
                }
            )

        up = down = limit_up = limit_down = None
        turnover_amount = None
        sentiment = None
        try:
            stocks = await self._market_snapshot()
            valid = [s for s in stocks if s.get("change") is not None]
            up = sum(1 for s in valid if float(s.get("change") or 0) > 0)
            down = sum(1 for s in valid if float(s.get("change") or 0) < 0)
            limit_up = 0
            limit_down = 0
            for s in valid:
                change = float(s.get("change") or 0)
                threshold = self._limit_threshold(str(s.get("code") or ""), str(s.get("name") or ""))
                if change >= threshold:
                    limit_up += 1
                if change <= -threshold:
                    limit_down += 1
            total_yi = sum(float(s.get("amount") or 0) for s in stocks)
            turnover_amount = round(total_yi / 10000, 2)
            total = up + down
            sentiment = round(up / total * 100, 1) if total else None
        except Exception:
            pass

        return {
            "indexes": indexes,
            "up": up,
            "down": down,
            "limit_up": limit_up,
            "limit_down": limit_down,
            "turnover_amount": turnover_amount,
            "sentiment": sentiment,
            "updated_at": time.strftime("%H:%M:%S"),
        }

    async def stocks(self):
        try:
            rows = await self._market_enriched()
            if not rows:
                rows = await self._market_snapshot()
            rows = list(rows)
            rows.sort(
                key=lambda x: (
                    x.get("main_inflow") if x.get("main_inflow") is not None else float("-inf"),
                    x.get("amount") or 0,
                ),
                reverse=True,
            )
            return rows[:300]
        except Exception:
            raw = await self.realtime(IFIND_WATCHLIST, "latest,changeRatio,amount")
            rows = self.rows_from_response(raw)
            result = []
            for r in rows:
                item = self.normalize_stock_row(r)
                item["reasons"] = ["iFinD 实时行情；问财字段暂未返回"]
                result.append(item)
            return result

    async def fund_industries(self):
        try:
            rows = await self._market_enriched()
            if not rows:
                return []
            has_industry = any((r.get("industry") not in (None, "", "—")) for r in rows)
            has_inflow = any(r.get("main_inflow") is not None for r in rows)
            if not has_industry or not has_inflow:
                return []

            agg: dict[str, dict[str, float]] = {}
            for r in rows:
                industry = r.get("industry") or "未分类"
                if industry == "—":
                    continue
                bucket = agg.setdefault(
                    industry,
                    {"main_inflow": 0.0, "amount": 0.0, "up": 0.0, "count": 0.0},
                )
                bucket["main_inflow"] += float(r.get("main_inflow") or 0)
                bucket["amount"] += float(r.get("amount") or 0)
                bucket["count"] += 1
                if (r.get("change") or 0) > 0:
                    bucket["up"] += 1

            result = []
            for industry, v in agg.items():
                result.append(
                    {
                        "industry": industry,
                        "main_inflow": v["main_inflow"],
                        "amount": v["amount"],
                        "up_ratio": round(v["up"] / v["count"] * 100, 1) if v["count"] else 0,
                    }
                )
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
        item.update(
            {
                "code": code,
                "reasons": [
                    f"开 {r.get('open')} / 高 {r.get('high')} / 低 {r.get('low')}",
                    "iFinD 实时行情",
                ],
                "fund_timeline": [],
            }
        )

        # 基础问财与扩展字段完全拆开，任何一个扩展失败都不影响个股基础数据。
        try:
            basic = await self.wencai_stocks(
                f"{code}，收盘价，今日涨跌幅，今日成交额，今日换手率，今日量比"
            )
            if basic:
                base = basic[0]
                for key in ("name", "price", "change", "amount", "turnover", "volume_ratio"):
                    if base.get(key) is not None:
                        item[key] = base.get(key)
        except Exception:
            pass

        optional_queries = [
            (f"{code}，所属同花顺行业", ("industry",)),
            (f"{code}，今日主力净流入", ("main_inflow",)),
            (f"{code}，今日主力净流入率", ("main_inflow_rate",)),
        ]
        for query, keys in optional_queries:
            try:
                extra = await self.wencai_stocks(query)
                if not extra:
                    continue
                for key in keys:
                    value = extra[0].get(key)
                    if value not in (None, "", "—"):
                        item[key] = value
            except Exception:
                continue

        score, reasons, risks = score_stock(item)
        item["score"] = score
        if reasons:
            item["reasons"] = item["reasons"] + reasons
        item["risks"] = risks
        return item

    async def _diagnose_one(self, query: str) -> dict[str, Any]:
        try:
            raw = await self.wencai(query)
            rows = self.rows_from_response(raw)
            return {
                "ok": True,
                "query": query,
                "errorcode": raw.get("errorcode"),
                "errmsg": raw.get("errmsg"),
                "row_count": len(rows),
                "rows_preview": rows[:2],
            }
        except Exception as e:
            return {
                "ok": False,
                "query": query,
                "error": str(e),
            }

    async def diagnose(self):
        realtime_raw = await self.realtime(["300033.SZ"], "latest,changeRatio,amount")
        tests = {
            "basic": await self._diagnose_one(
                "300033.SZ，收盘价，今日涨跌幅，今日成交额，今日换手率，今日量比"
            ),
            "industry": await self._diagnose_one("300033.SZ，所属同花顺行业"),
            "main_inflow": await self._diagnose_one("300033.SZ，今日主力净流入"),
            "main_inflow_rate": await self._diagnose_one("300033.SZ，今日主力净流入率"),
            "market_basic": await self._diagnose_one(
                "A股，股票代码，股票简称，收盘价，今日涨跌幅，今日成交额，今日换手率，今日量比"
            ),
        }
        return {
            "mode": "ifind",
            "realtime_errorcode": realtime_raw.get("errorcode"),
            "realtime_table_count": len(realtime_raw.get("tables") or []),
            "realtime_rows": self.rows_from_response(realtime_raw)[:2],
            "tests": tests,
            "optional_errors": dict(self._optional_errors),
        }
