# fin-lab-vibe

A personal financial intelligence dashboard built with Flask, focused on market regimes, cross-asset signals, valuation comparisons, and single-stock snapshots.

## Run locally

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

Then open http://127.0.0.1:5050.

## What is included

- Cross-asset dashboard for GLD, volatility, and 10Y TIPS real yield.
- Macro pulse cards for VIX, Treasury yields, spread, sentiment, and yield curve.
- Valuation lab for major tech stocks.
- Single-stock lookup by ticker.
- A reserved `/api/portfolio` endpoint for future position tracking.

## Data source notes

The first version uses Yahoo Finance public chart/quote endpoints and FRED CSV data. TradingView integration is intentionally kept behind the data layer decision so it can be added later without rewriting the UI.
