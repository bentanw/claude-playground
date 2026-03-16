#!/usr/bin/env python3
"""
Market scanner — finds momentum candidates from the scan universe.
Usage: python3 discover.py [--top N] [--universe TICKER1,TICKER2,...]
Outputs ranked JSON list to stdout.
"""

import json
import sys
import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

_DIR = __import__("os").environ.get("PORTFOLIO_DIR", "outputs/portfolio-trader")
CONFIG_PATH = f"{_DIR}/config.json"
DATA_PATH = f"{_DIR}/data.json"


def load_data() -> dict:
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    with open(DATA_PATH, "r") as f:
        runtime = json.load(f)
    runtime["account"] = {**config["account"], "cash": runtime["cash"]}
    runtime["strategy"] = config["strategy"]
    return runtime


def compute_rsi(closes: pd.Series, period: int = 14) -> float:
    """Wilder RSI using exponential moving average."""
    delta = closes.diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder smoothing: EMA with alpha = 1/period
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 1) if not rsi.empty else None


def market_cap_category(market_cap) -> str:
    if market_cap is None:
        return "unknown"
    if market_cap < 300_000_000:
        return "micro"
    elif market_cap < 2_000_000_000:
        return "small"
    elif market_cap < 10_000_000_000:
        return "mid"
    else:
        return "large"


def fetch_momentum_data(ticker_sym: str) -> dict | None:
    """Fetch 30d OHLCV and compute momentum metrics."""
    try:
        t = yf.Ticker(ticker_sym)
        hist = t.history(period="35d", auto_adjust=True)
        if hist is None or len(hist) < 10:
            return None

        closes = hist["Close"]
        volumes = hist["Volume"]

        current_price = round(float(closes.iloc[-1]), 4)
        price_1d_pct = round((float(closes.iloc[-1]) - float(closes.iloc[-2])) / float(closes.iloc[-2]) * 100, 2) if len(closes) >= 2 else None
        price_5d_pct = round((float(closes.iloc[-1]) - float(closes.iloc[-6])) / float(closes.iloc[-6]) * 100, 2) if len(closes) >= 6 else None

        avg_volume_20d = float(volumes.iloc[-21:-1].mean()) if len(volumes) >= 21 else float(volumes.mean())
        today_volume = float(volumes.iloc[-1])
        volume_ratio = round(today_volume / avg_volume_20d, 2) if avg_volume_20d > 0 else None

        sma_20 = closes.rolling(20).mean().iloc[-1]
        sma_50 = closes.rolling(50).mean().iloc[-1] if len(closes) >= 50 else None
        above_20d_ma = bool(current_price > float(sma_20)) if not pd.isna(sma_20) else None
        above_50d_ma = bool(current_price > float(sma_50)) if sma_50 is not None and not pd.isna(sma_50) else None

        rsi = compute_rsi(closes)

        # Market cap
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass
        mc = info.get("marketCap")
        cap_cat = market_cap_category(mc)

        return {
            "ticker": ticker_sym,
            "current_price": current_price,
            "price_1d_pct": price_1d_pct,
            "price_5d_pct": price_5d_pct,
            "volume_ratio": volume_ratio,
            "above_20d_ma": above_20d_ma,
            "above_50d_ma": above_50d_ma,
            "rsi_14": rsi,
            "market_cap": mc,
            "market_cap_category": cap_cat,
        }
    except Exception as e:
        return None


def score_candidate(metrics: dict, strategy: dict) -> tuple[float, list]:
    """Score ticker 0–100 for momentum buy setup. Returns (score, reasons)."""
    score = 0.0
    reasons = []

    vr = metrics.get("volume_ratio") or 0
    p5d = metrics.get("price_5d_pct") or 0
    rsi = metrics.get("rsi_14") or 50
    above_ma = metrics.get("above_20d_ma")
    cap = metrics.get("market_cap_category", "unknown")

    # Volume surge (+30 pts max)
    if vr >= 4:
        score += 30
        reasons.append(f"Volume {vr:.1f}x avg (very strong)")
    elif vr >= 2:
        pts = 15 + (vr - 2) / 2 * 15
        score += pts
        reasons.append(f"Volume {vr:.1f}x avg")
    elif vr >= 1.5:
        score += 10
        reasons.append(f"Volume {vr:.1f}x avg (moderate)")

    # Price momentum 3–15% sweet spot (+25 pts max)
    min_move = strategy.get("min_price_move_pct", 3.0)
    max_move = strategy.get("max_price_move_pct", 15.0)
    if min_move <= p5d <= max_move:
        score += 25
        reasons.append(f"5d momentum +{p5d:.1f}% (sweet spot)")
    elif 1 <= p5d < min_move:
        score += 10
        reasons.append(f"5d momentum +{p5d:.1f}% (weak)")
    elif -2 <= p5d < 1:
        score += 5  # flat, not great

    # Above 20d MA (+15 pts)
    if above_ma is True:
        score += 15
        reasons.append("Above 20d MA")
    elif above_ma is False:
        reasons.append("Below 20d MA")

    # RSI momentum zone 50–70 (+15 pts)
    if 50 <= rsi <= 70:
        score += 15
        reasons.append(f"RSI {rsi} (momentum zone)")
    elif 40 <= rsi < 50:
        score += 5
        reasons.append(f"RSI {rsi} (recovering)")
    elif rsi > 70:
        reasons.append(f"RSI {rsi} (elevated)")

    # Market cap preference (+15 pts)
    focus = strategy.get("focus_market_caps", ["small", "mid"])
    if cap in focus:
        score += 15
        reasons.append(f"{cap.capitalize()} cap (preferred)")
    elif cap == "large":
        score += 5

    # Penalties
    if rsi > 75:
        score -= 20
        reasons.append(f"PENALTY: RSI {rsi} overbought")
    if p5d > 20:
        score -= 20
        reasons.append(f"PENALTY: 5d +{p5d:.1f}% likely exhausted")
    if vr < 1.5 and vr > 0:
        score -= 10
        reasons.append(f"PENALTY: Low volume {vr:.1f}x")

    return round(max(0, min(100, score)), 1), reasons


def scan(universe: list, strategy: dict, top_n: int = 10) -> list:
    """Scan universe, score, return top_n ranked candidates."""
    results = []
    for ticker in universe:
        metrics = fetch_momentum_data(ticker)
        if metrics is None:
            continue
        score, reasons = score_candidate(metrics, strategy)
        entry = {**metrics, "score": score, "signal_summary": " | ".join(reasons)}
        results.append(entry)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=8)
    parser.add_argument("--universe", type=str, default=None,
                        help="Comma-separated tickers (default: read from data.json)")
    args = parser.parse_args()

    data = load_data()
    strategy = data["strategy"]

    if args.universe:
        universe = [t.strip().upper() for t in args.universe.split(",")]
        sector_map = {}
    else:
        raw = strategy.get("scan_universe", [])
        if isinstance(raw, dict):
            # Sector-based: flatten and build reverse lookup {ticker: sector}
            sector_map = {}
            flat = []
            for sector, tickers in raw.items():
                for t in tickers:
                    sector_map[t.upper()] = sector
                    flat.append(t.upper())
            universe = list(dict.fromkeys(flat))
        else:
            universe = [t.upper() for t in raw]
            sector_map = {}
        # Also include watchlist tickers
        watchlist_tickers = [w["ticker"] for w in data.get("watchlist", [])]
        universe = list(dict.fromkeys(universe + watchlist_tickers))

    candidates = scan(universe, strategy, top_n=args.top)

    # Tag each candidate with its sector
    for c in candidates:
        c["sector"] = sector_map.get(c["ticker"], "other")

    output = {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scanned": len(universe),
        "returned": len(candidates),
        "candidates": candidates
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
