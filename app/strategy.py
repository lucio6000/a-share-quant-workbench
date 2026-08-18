from __future__ import annotations

from typing import Any


def build_wencai_query(criteria: dict[str, Any]) -> str:
    parts: list[str] = ["A股"]
    if criteria.get("exclude_st", True):
        parts.append("非ST")
    if criteria.get("min_amount") is not None:
        parts.append(f"今日成交额大于{criteria['min_amount']}亿元")
    if criteria.get("min_turnover") is not None:
        parts.append(f"今日换手率大于{criteria['min_turnover']}%")
    if criteria.get("max_turnover") is not None:
        parts.append(f"今日换手率小于{criteria['max_turnover']}%")
    if criteria.get("min_volume_ratio") is not None:
        parts.append(f"今日量比大于{criteria['min_volume_ratio']}")
    if criteria.get("min_change") is not None:
        parts.append(f"今日涨跌幅大于{criteria['min_change']}%")
    if criteria.get("max_change") is not None:
        parts.append(f"今日涨跌幅小于{criteria['max_change']}%")
    if criteria.get("min_main_inflow") is not None:
        parts.append(f"今日主力净流入大于{criteria['min_main_inflow']}万元")
    if criteria.get("price_above_ma20"):
        parts.append("股价高于20日均线")
    if criteria.get("ma20_up"):
        parts.append("20日均线向上")
    return "，".join(parts)


def score_stock(s: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    score = 50
    reasons: list[str] = []
    risks: list[str] = []
    inflow = float(s.get("main_inflow", 0) or 0)
    inflow_rate = float(s.get("main_inflow_rate", 0) or 0)
    change = float(s.get("change", 0) or 0)
    turnover = float(s.get("turnover", 0) or 0)
    vr = float(s.get("volume_ratio", 0) or 0)
    ma20_gap = float(s.get("ma20_gap", 0) or 0)

    if inflow >= 10000:
        score += 15; reasons.append("主力净流入超过1亿元")
    elif inflow >= 5000:
        score += 10; reasons.append("主力净流入超过5000万元")
    elif inflow < 0:
        score -= 12; risks.append("主力资金净流出")
    if inflow_rate >= 5:
        score += 10; reasons.append("主力净流入率较高")
    elif inflow_rate < 0:
        score -= 6
    if 3 <= turnover <= 12:
        score += 6; reasons.append("换手率处于活跃区间")
    elif turnover > 20:
        score -= 6; risks.append("换手率过高")
    if vr >= 1.5:
        score += 7; reasons.append("成交明显放量")
    elif vr < 0.7:
        score -= 3
    if ma20_gap > 0:
        score += 7; reasons.append("股价位于MA20上方")
    else:
        score -= 5; risks.append("股价仍在MA20下方")
    if change > 8:
        score -= 5; risks.append("日内涨幅较大，追高风险上升")
    elif 0 < change <= 7:
        score += 3
    return max(0, min(100, int(round(score)))), reasons, risks


def matches(s: dict[str, Any], c: dict[str, Any]) -> bool:
    checks = [
        float(s.get("amount", 0)) >= float(c.get("min_amount", 0) or 0),
        float(s.get("turnover", 0)) >= float(c.get("min_turnover", 0) or 0),
        float(s.get("turnover", 0)) <= float(c.get("max_turnover", 999) or 999),
        float(s.get("volume_ratio", 0)) >= float(c.get("min_volume_ratio", 0) or 0),
        float(s.get("change", 0)) >= float(c.get("min_change", -99) if c.get("min_change") is not None else -99),
        float(s.get("change", 0)) <= float(c.get("max_change", 99) if c.get("max_change") is not None else 99),
        float(s.get("main_inflow", 0)) >= float(c.get("min_main_inflow", -999999) if c.get("min_main_inflow") is not None else -999999),
    ]
    if c.get("price_above_ma20"):
        checks.append(float(s.get("ma20_gap", -999)) > 0)
    if c.get("ma20_up"):
        checks.append(bool(s.get("ma20_up", False)))
    if c.get("exclude_st", True):
        checks.append("ST" not in str(s.get("name", "")).upper())
    return all(checks)
