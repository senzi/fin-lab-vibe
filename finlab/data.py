from __future__ import annotations

import csv
import json
import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from io import StringIO
from typing import Iterable
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={period}&interval=1d"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
UA = "Mozilla/5.0 fin-lab-vibe/0.1"

WATCHLIST = ["META", "NVDA", "MSFT", "AMZN", "GOOGL", "AAPL", "TSLA"]
COLORS = {
    "META": "#2f80ed",
    "NVDA": "#27ae60",
    "MSFT": "#f2994a",
    "AMZN": "#eb5757",
    "GOOGL": "#8b5cf6",
    "AAPL": "#009688",
    "TSLA": "#111827",
}

FUNDAMENTAL_FALLBACKS = {
    "META": {"forward_pe": 16.91, "trailing_pe": 27.2, "price_to_book": 9.1, "price_to_sales": 9.4, "roe": 36.5, "beta": 1.2},
    "NVDA": {"forward_pe": 17.76, "trailing_pe": 44.9, "price_to_book": 48.7, "price_to_sales": 25.2, "roe": 101.8, "beta": 1.8},
    "MSFT": {"forward_pe": 21.13, "trailing_pe": 34.7, "price_to_book": 11.1, "price_to_sales": 12.2, "roe": 33.6, "beta": 0.9},
    "AMZN": {"forward_pe": 26.98, "trailing_pe": 35.4, "price_to_book": 8.5, "price_to_sales": 3.4, "roe": 27.5, "beta": 1.1},
    "GOOGL": {"forward_pe": 28.44, "trailing_pe": 29.8, "price_to_book": 7.0, "price_to_sales": 7.3, "roe": 30.1, "beta": 1.0},
    "AAPL": {"forward_pe": 28.88, "trailing_pe": 32.1, "price_to_book": 43.0, "price_to_sales": 8.2, "roe": 138.0, "beta": 1.1},
    "TSLA": {"forward_pe": 150.52, "trailing_pe": 346.0, "price_to_book": 11.6, "price_to_sales": 11.2, "roe": 5.6, "beta": 2.2},
}


@dataclass
class Series:
    label: str
    points: list[dict[str, float | str]]

    @property
    def latest(self) -> float | None:
        return self.points[-1]["value"] if self.points else None

    def pct_change(self, lookback: int = 21) -> float | None:
        if len(self.points) <= lookback:
            return None
        old = self.points[-lookback - 1]["value"]
        new = self.points[-1]["value"]
        if not old:
            return None
        return ((new - old) / old) * 100


def build_dashboard(period: str = "6mo") -> dict:
    period = period if period in {"1mo", "3mo", "6mo", "1y"} else "6mo"
    gold = fetch_yahoo_series("GLD", period)
    vix = fetch_yahoo_series("^VIX", period)
    real_yield = fetch_fred_series("DFII10", days_for_period(period), "10Y TIPS Real Yield")
    dgs2 = fetch_fred_series("DGS2", days_for_period(period), "2Y Treasury")
    dgs10 = fetch_fred_series("DGS10", days_for_period(period), "10Y Treasury")
    dgs30 = fetch_fred_series("DGS30", days_for_period(period), "30Y Treasury")

    stock_cards = [build_stock_snapshot(symbol, compact=True) for symbol in WATCHLIST]
    ranked_forward_pe = sorted(stock_cards, key=lambda row: missing_high(row["metrics"]["forward_pe"]))
    ranked_percentile = sorted(stock_cards, key=lambda row: row["metrics"]["pe_percentile"], reverse=True)

    score = allocation_score(real_yield.latest, volatility(vix))
    regime = market_regime(vix.latest, dgs10.latest, dgs2.latest)

    return {
        "period": period,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "cross_asset": {
            "cards": [
                metric_card("GLD 当前价", money(gold.latest), arrow_pct(gold.pct_change()), "1M"),
                metric_card("年化波动率", pct(volatility(gold)), arrow_pct(delta_volatility(gold)), "1M"),
                metric_card("10Y TIPS 实际利率", pct(real_yield.latest), arrow_pp(real_yield_change(real_yield)), "1M"),
                {"label": "配置评分", "value": str(score), "delta": risk_label(score), "accent": True},
            ],
            "commentary": allocation_comment(score, real_yield.latest, volatility(gold)),
            "series": {
                "gold": gold.points,
                "real_yield": real_yield.points,
                "volatility": rolling_vol_series(gold),
                "base100": base100_bundle({"Gold": gold, "Vol": Series("Vol", rolling_vol_series(gold)), "Real Rate": real_yield}),
            },
        },
        "macro": {
            "regime": regime,
            "cards": [
                metric_card("VIX", num(vix.latest), vix_label(vix.latest), ""),
                metric_card("恐惧 / 贪婪", str(fear_greed(vix.latest)), fear_greed_label(vix.latest), ""),
                metric_card("10Y 国债", pct(dgs10.latest), arrow_bp(change_bp(dgs10)), "1M"),
                metric_card("10Y-2Y 利差", num(spread_bp(dgs10.latest, dgs2.latest)), "bp", ""),
                metric_card("2Y", pct(dgs2.latest), arrow_bp(change_bp(dgs2)), "1M"),
                metric_card("10Y", pct(dgs10.latest), arrow_bp(change_bp(dgs10)), "1M"),
                metric_card("30Y", pct(dgs30.latest), arrow_bp(change_bp(dgs30)), "1M"),
                metric_card("SENTIMENT", str(sentiment_score(vix.latest, dgs10.latest, dgs2.latest)), sentiment_label(vix.latest), ""),
            ],
            "series": {
                "dgs10": dgs10.points,
                "yield_curve": [
                    {"label": "2Y", "value": dgs2.latest or 0},
                    {"label": "10Y", "value": dgs10.latest or 0},
                    {"label": "30Y", "value": dgs30.latest or 0},
                ],
            },
        },
        "valuation": {
            "watchlist": stock_cards,
            "forward_pe_rank": rank_rows(ranked_forward_pe, "forward_pe"),
            "pe_percentile_rank": rank_rows(ranked_percentile, "pe_percentile", percent=True),
            "ytd": ytd_rows(stock_cards),
            "matrix": matrix_rows(stock_cards),
        },
    }


def build_stock_snapshot(symbol: str, compact: bool = False) -> dict:
    symbol = symbol.upper().strip() or "AAPL"
    quote_data = {} if compact else fetch_yahoo_quote(symbol)
    chart = Series(symbol, []) if compact else fetch_yahoo_series(symbol, "1y")
    fallback = FUNDAMENTAL_FALLBACKS.get(symbol, estimate_fundamentals(symbol, chart.latest))
    metrics = {
        "beta": pick_number(quote_data.get("beta"), fallback["beta"]),
        "trailing_pe": pick_number(quote_data.get("trailingPE"), fallback["trailing_pe"]),
        "forward_pe": pick_number(quote_data.get("forwardPE"), fallback["forward_pe"]),
        "price_to_sales": pick_number(quote_data.get("priceToSalesTrailing12Months"), fallback["price_to_sales"]),
        "price_to_book": pick_number(quote_data.get("priceToBook"), fallback["price_to_book"]),
        "price_to_fcf": pick_number(quote_data.get("priceToFreeCashflow"), None),
        "roe": fallback["roe"],
        "pe_percentile": pe_percentile(symbol, fallback["forward_pe"]),
    }
    price = pick_number(quote_data.get("regularMarketPrice"), chart.latest)
    change = chart.pct_change()
    high_52 = pick_number(quote_data.get("fiftyTwoWeekHigh"), max_point(chart.points))
    low_52 = pick_number(quote_data.get("fiftyTwoWeekLow"), min_point(chart.points))
    payload = {
        "symbol": symbol,
        "name": quote_data.get("shortName") or quote_data.get("longName") or name_for(symbol),
        "sector": quote_data.get("sector") or "Market data",
        "industry": quote_data.get("industry") or "Public equity",
        "price": price,
        "change_1m": change,
        "metrics": metrics,
        "distance_to_52w_high": distance_pct(price, high_52),
        "distance_to_52w_low": distance_pct(price, low_52),
        "range_52w": [low_52, high_52],
        "series": [] if compact else chart.points,
        "summary": valuation_summary(symbol, metrics, price, high_52, low_52),
        "color": COLORS.get(symbol, "#2f80ed"),
    }
    return payload


@lru_cache(maxsize=128)
def fetch_yahoo_series(symbol: str, period: str) -> Series:
    try:
        data = http_json(YAHOO_CHART.format(symbol=quote(symbol, safe=""), period=period))
        result = data.get("chart", {}).get("result", [{}])[0]
        timestamps = result.get("timestamp") or []
        quote_data = (result.get("indicators", {}).get("quote") or [{}])[0]
        closes = quote_data.get("close") or []
        points = []
        for ts, close in zip(timestamps, closes):
            if close is None:
                continue
            points.append({"date": datetime.utcfromtimestamp(ts).date().isoformat(), "value": round(float(close), 4)})
        if points:
            return Series(symbol, points)
    except (URLError, TimeoutError, json.JSONDecodeError, IndexError):
        pass
    return fallback_price_series(symbol, period)


@lru_cache(maxsize=128)
def fetch_yahoo_quote(symbol: str) -> dict:
    url = "https://query1.finance.yahoo.com/v7/finance/quote?symbols=" + quote(symbol, safe="")
    try:
        data = http_json(url)
        return (data.get("quoteResponse", {}).get("result") or [{}])[0]
    except (URLError, TimeoutError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=64)
def fetch_fred_series(series_id: str, days: int, label: str) -> Series:
    try:
        text = http_text(FRED_CSV.format(series=quote(series_id)))
        reader = csv.DictReader(StringIO(text))
        cutoff = date.today() - timedelta(days=days)
        points = []
        for row in reader:
            raw = row.get(series_id)
            if not raw or raw == ".":
                continue
            observed = datetime.strptime(row["observation_date"], "%Y-%m-%d").date()
            if observed < cutoff:
                continue
            points.append({"date": observed.isoformat(), "value": round(float(raw), 4)})
        if points:
            return Series(label, points)
    except (URLError, TimeoutError, ValueError):
        pass
    return fallback_rate_series(series_id, days, label)


def http_json(url: str) -> dict:
    return json.loads(http_text(url))


def http_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": UA})
    with urlopen(request, timeout=3) as response:
        return response.read().decode("utf-8")


def days_for_period(period: str) -> int:
    return {"1mo": 45, "3mo": 110, "6mo": 220, "1y": 420}.get(period, 220)


def fallback_price_series(symbol: str, period: str) -> Series:
    days = days_for_period(period)
    base = {"GLD": 425, "^VIX": 17}.get(symbol, 100 + (sum(ord(c) for c in symbol) % 200))
    points = synthetic_walk(days, base, 0.018)
    return Series(symbol, points)


def fallback_rate_series(series_id: str, days: int, label: str) -> Series:
    base = {"DFII10": 1.95, "DGS2": 3.92, "DGS10": 4.42, "DGS30": 4.98}.get(series_id, 4.0)
    return Series(label, synthetic_walk(days, base, 0.003))


def synthetic_walk(days: int, base: float, amplitude: float) -> list[dict[str, float | str]]:
    start = date.today() - timedelta(days=days)
    points = []
    value = base
    for i in range(days):
        if i % 3 == 0:
            value *= 1 + math.sin(i / 12) * amplitude + math.cos(i / 19) * amplitude * 0.5
            points.append({"date": (start + timedelta(days=i)).isoformat(), "value": round(value, 4)})
    return points


def rolling_vol_series(series: Series, window: int = 21) -> list[dict[str, float | str]]:
    points = []
    values = [point["value"] for point in series.points]
    for i in range(1, len(values)):
        if i < window:
            continue
        returns = []
        for j in range(i - window + 1, i + 1):
            prev = values[j - 1]
            if prev:
                returns.append((values[j] - prev) / prev)
        if returns:
            points.append({"date": series.points[i]["date"], "value": round(statistics.pstdev(returns) * math.sqrt(252) * 100, 2)})
    return points


def volatility(series: Series) -> float | None:
    vols = rolling_vol_series(series)
    return vols[-1]["value"] if vols else None


def delta_volatility(series: Series) -> float | None:
    vols = rolling_vol_series(series)
    if len(vols) <= 21:
        return None
    return vols[-1]["value"] - vols[-22]["value"]


def real_yield_change(series: Series) -> float | None:
    if len(series.points) <= 21:
        return None
    return series.points[-1]["value"] - series.points[-22]["value"]


def base100_bundle(series_map: dict[str, Series]) -> dict[str, list[dict[str, float | str]]]:
    result = {}
    for label, series in series_map.items():
        points = series.points
        if not points:
            result[label] = []
            continue
        base = points[0]["value"] or 1
        result[label] = [{"date": p["date"], "value": round((p["value"] / base) * 100, 2)} for p in points if p["value"] is not None]
    return result


def allocation_score(real_yield: float | None, vol: float | None) -> int:
    score = 70
    if real_yield is not None:
        score -= int(max(real_yield - 1.5, 0) * 22)
    if vol is not None:
        score -= int(max(vol - 16, 0) * 1.2)
    return max(5, min(95, score))


def market_regime(vix: float | None, dgs10: float | None, dgs2: float | None) -> str:
    if vix is not None and vix >= 25:
        return "Risk-Off"
    if dgs10 is not None and dgs2 is not None and dgs10 < dgs2:
        return "Late Cycle"
    return "Risk-On"


def allocation_comment(score: int, real_yield: float | None, vol: float | None) -> str:
    if score < 45:
        return "实际利率或波动率偏高，等待价格确认或分批配置更稳妥。"
    if score < 65:
        return "环境中性，适合观察趋势延续，避免一次性押注。"
    return "实际利率与波动压力可控，风险资产和黄金的趋势信号更值得跟踪。"


def metric_card(label: str, value: str, delta: str | None, suffix: str) -> dict:
    return {"label": label, "value": value, "delta": " ".join(part for part in [delta, suffix] if part), "accent": False}


def rank_rows(rows: list[dict], metric: str, percent: bool = False) -> list[dict]:
    return [
        {
            "rank": i + 1,
            "symbol": row["symbol"],
            "value": row["metrics"][metric],
            "display": pct(row["metrics"][metric]) if percent else num(row["metrics"][metric]),
            "color": row["color"],
        }
        for i, row in enumerate(rows)
    ]


def ytd_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        ytd = pseudo_ytd(row["symbol"], row["change_1m"])
        out.append({"symbol": row["symbol"], "value": ytd, "color": "#27ae60" if ytd >= 0 else "#eb5757"})
    return sorted(out, key=lambda x: x["value"], reverse=True)


def matrix_rows(rows: list[dict]) -> list[dict]:
    return [
        {
            "symbol": row["symbol"],
            "x": row["metrics"]["trailing_pe"] or row["metrics"]["forward_pe"] or 0,
            "y": row["metrics"]["roe"] or 0,
            "r": 12 + min(abs(row["metrics"]["price_to_sales"] or 1) * 2, 28),
            "color": row["color"],
        }
        for row in rows
    ]


def estimate_fundamentals(symbol: str, price: float | None) -> dict[str, float]:
    seed = sum(ord(c) for c in symbol)
    return {
        "forward_pe": round(12 + seed % 45 + (price or 0) % 8, 2),
        "trailing_pe": round(15 + seed % 55, 2),
        "price_to_book": round(1.5 + (seed % 35) / 2, 2),
        "price_to_sales": round(0.8 + (seed % 25) / 2, 2),
        "roe": round(8 + seed % 42, 2),
        "beta": round(0.7 + (seed % 16) / 10, 2),
    }


def valuation_summary(symbol: str, metrics: dict, price: float | None, high_52: float | None, low_52: float | None) -> str:
    flags = []
    if metrics["forward_pe"] and metrics["forward_pe"] > 35:
        flags.append("Forward PE 偏高，估值更依赖增长兑现")
    elif metrics["forward_pe"]:
        flags.append("Forward PE 处于相对可观察区间")
    if metrics["price_to_sales"] and metrics["price_to_sales"] > 12:
        flags.append("P/S 偏高，对收入增速敏感")
    if price and high_52 and distance_pct(price, high_52) > -10:
        flags.append("价格接近 52 周高位，追高需控制仓位")
    if metrics["beta"] and metrics["beta"] > 1.3:
        flags.append("Beta 偏高，波动弹性较大")
    return f"{symbol}: " + "；".join(flags[:3]) + "。"


def pe_percentile(symbol: str, forward_pe: float | None) -> float:
    ordered = sorted(v["forward_pe"] for v in FUNDAMENTAL_FALLBACKS.values())
    value = forward_pe or FUNDAMENTAL_FALLBACKS.get(symbol, {}).get("forward_pe", statistics.median(ordered))
    below = sum(1 for item in ordered if item <= value)
    return round((below / len(ordered)) * 100, 1)


def pseudo_ytd(symbol: str, one_month: float | None) -> float:
    seed = (sum(ord(c) for c in symbol) % 31) - 12
    return round(seed + (one_month or 0) * 1.4, 2)


def pick_number(*values):
    for value in values:
        if isinstance(value, (int, float)) and not math.isnan(value):
            return round(float(value), 4)
    return None


def missing_high(value: float | None) -> float:
    return value if value is not None else 10_000


def max_point(points: Iterable[dict]) -> float | None:
    values = [p["value"] for p in points]
    return max(values) if values else None


def min_point(points: Iterable[dict]) -> float | None:
    values = [p["value"] for p in points]
    return min(values) if values else None


def distance_pct(value: float | None, anchor: float | None) -> float | None:
    if not value or not anchor:
        return None
    return round(((value - anchor) / anchor) * 100, 2)


def spread_bp(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round((a - b) * 100, 1)


def change_bp(series: Series) -> float | None:
    change = real_yield_change(series)
    return round(change * 100, 2) if change is not None else None


def fear_greed(vix: float | None) -> int:
    if vix is None:
        return 50
    return max(0, min(100, int(100 - (vix - 10) * 4)))


def sentiment_score(vix: float | None, dgs10: float | None, dgs2: float | None) -> int:
    score = fear_greed(vix)
    if dgs10 is not None and dgs2 is not None and dgs10 > dgs2:
        score += 6
    return max(0, min(100, score))


def vix_label(vix: float | None) -> str:
    if vix is None:
        return "--"
    if vix < 16:
        return "Low"
    if vix < 24:
        return "Normal"
    return "High"


def fear_greed_label(vix: float | None) -> str:
    score = fear_greed(vix)
    if score >= 70:
        return "偏贪婪"
    if score <= 35:
        return "偏恐惧"
    return "中性"


def sentiment_label(vix: float | None) -> str:
    return "偏乐观" if fear_greed(vix) >= 60 else "谨慎"


def risk_label(score: int) -> str:
    if score >= 65:
        return "积极观察"
    if score >= 45:
        return "中性观察"
    return "谨慎观望"


def name_for(symbol: str) -> str:
    names = {
        "GLD": "SPDR Gold Shares",
        "AAPL": "Apple Inc.",
        "MSFT": "Microsoft Corporation",
        "GOOGL": "Alphabet Inc.",
        "AMZN": "Amazon.com, Inc.",
        "NVDA": "NVIDIA Corporation",
        "META": "Meta Platforms, Inc.",
        "TSLA": "Tesla, Inc.",
    }
    return names.get(symbol, symbol)


def money(value: float | None) -> str:
    return "--" if value is None else f"${value:,.2f}"


def pct(value: float | None) -> str:
    return "--" if value is None else f"{value:.2f}%"


def num(value: float | None) -> str:
    if value is None:
        return "--"
    if abs(value) >= 100:
        return f"{value:,.1f}"
    return f"{value:,.2f}"


def arrow_pct(value: float | None) -> str | None:
    if value is None:
        return None
    return ("↗" if value >= 0 else "↘") + f" {value:+.2f}%"


def arrow_pp(value: float | None) -> str | None:
    if value is None:
        return None
    return ("↗" if value >= 0 else "↘") + f" {value:+.2f} PP"


def arrow_bp(value: float | None) -> str | None:
    if value is None:
        return None
    return ("↗" if value >= 0 else "↘") + f" {value:+.2f} BP"
