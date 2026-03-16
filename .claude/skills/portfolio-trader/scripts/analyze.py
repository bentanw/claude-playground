#!/usr/bin/env python3
"""
Deep analysis engine — fetches rich per-ticker data for Claude's decision-making.
Usage: python3 analyze.py TICKER1 TICKER2 ...
Outputs structured JSON to stdout.
"""

import json
import sys
import argparse
from datetime import datetime, timezone, date, timedelta

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


def compute_rsi(closes: pd.Series, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    delta = closes.diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 1) if not pd.isna(val) else None


def fetch_news_7d(ticker_obj) -> list:
    """Fetch news from last 7 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    results = []
    try:
        raw = ticker_obj.news or []
        for item in raw[:20]:
            content = item.get("content") or item
            title = content.get("title") or item.get("title", "")
            publisher = (content.get("provider") or {}).get("displayName") or item.get("publisher", "")
            pub_date_str = content.get("pubDate") or content.get("displayTime")
            pub_dt = None
            if pub_date_str:
                try:
                    pub_dt = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                except ValueError:
                    pass
            if pub_dt is None:
                ts = item.get("providerPublishTime") or item.get("pubTime")
                if ts:
                    pub_dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            if pub_dt and pub_dt >= cutoff and title:
                results.append(f"[{pub_dt.strftime('%m/%d')}] {title} ({publisher})")
            if len(results) >= 5:
                break
    except Exception:
        pass
    return results


def earnings_proximity_warning(ticker_obj) -> str | None:
    """Return warning string if earnings within 10 trading days."""
    try:
        cal = ticker_obj.calendar
        if cal is None:
            return None
        # Handle both dict and DataFrame
        if hasattr(cal, "to_dict"):
            cal = cal.to_dict()
        earnings_date = cal.get("Earnings Date") or cal.get("earningsDate")
        if earnings_date is None:
            return None
        if isinstance(earnings_date, list):
            earnings_date = earnings_date[0]
        if hasattr(earnings_date, "date"):
            earnings_date = earnings_date.date()
        elif isinstance(earnings_date, str):
            earnings_date = date.fromisoformat(earnings_date[:10])
        days_until = (earnings_date - date.today()).days
        if 0 <= days_until <= 10:
            return f"EARNINGS IN {days_until} DAYS ({earnings_date}) — HIGH RISK"
        elif 11 <= days_until <= 21:
            return f"Earnings in {days_until} days ({earnings_date}) — plan exit"
    except Exception:
        pass
    return None


def r(v, decimals=2):
    try:
        return round(float(v), decimals) if v is not None else None
    except (TypeError, ValueError):
        return None


def fetch_analysis(ticker_sym: str, held_position: dict = None) -> dict:
    """Full analysis for a single ticker."""
    result = {"ticker": ticker_sym, "error": None}
    try:
        t = yf.Ticker(ticker_sym)
        hist = t.history(period="60d", auto_adjust=True)
        if hist is None or len(hist) < 5:
            result["error"] = "Insufficient history"
            return result

        closes = hist["Close"]
        volumes = hist["Volume"]

        current_price = round(float(closes.iloc[-1]), 4)
        price_1d_pct = r((float(closes.iloc[-1]) - float(closes.iloc[-2])) / float(closes.iloc[-2]) * 100) if len(closes) >= 2 else None
        price_5d_pct = r((float(closes.iloc[-1]) - float(closes.iloc[-6])) / float(closes.iloc[-6]) * 100) if len(closes) >= 6 else None

        avg_vol_20d = float(volumes.iloc[-21:-1].mean()) if len(volumes) >= 21 else float(volumes.mean())
        today_vol = float(volumes.iloc[-1])
        volume_ratio = r(today_vol / avg_vol_20d) if avg_vol_20d > 0 else None

        sma_20 = float(closes.rolling(20).mean().iloc[-1])
        sma_50_series = closes.rolling(50).mean()
        sma_50 = float(sma_50_series.iloc[-1]) if len(closes) >= 50 else None

        above_20d_ma = bool(current_price > sma_20) if not pd.isna(sma_20) else None
        above_50d_ma = bool(current_price > sma_50) if sma_50 and not pd.isna(sma_50) else None

        rsi = compute_rsi(closes)

        # Fetch info
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass

        mc = info.get("marketCap")
        w52_high = r(info.get("fiftyTwoWeekHigh"))
        w52_low = r(info.get("fiftyTwoWeekLow"))
        analyst_target = r(info.get("targetMeanPrice"))
        short_float = r(info.get("shortPercentOfFloat"), 4)
        inst_ownership = r(info.get("heldPercentInstitutions"), 4)
        beta = r(info.get("beta"))

        dist_from_52w_high = r((current_price - w52_high) / w52_high * 100) if w52_high else None
        analyst_upside = r((analyst_target - current_price) / current_price * 100) if analyst_target else None

        earnings_warn = earnings_proximity_warning(t)
        news = fetch_news_7d(t)

        # Position context (if held)
        position_info = None
        if held_position:
            avg_cost = held_position["avg_cost"]
            stop_loss = held_position.get("stop_loss")
            take_profit = held_position.get("take_profit")
            pnl_pct = r((current_price - avg_cost) / avg_cost * 100)
            dist_to_stop = r((stop_loss - current_price) / current_price * 100) if stop_loss else None
            dist_to_target = r((take_profit - current_price) / current_price * 100) if take_profit else None
            try:
                entry_dt = date.fromisoformat(held_position["entry_date"])
                hold_days = (date.today() - entry_dt).days
            except Exception:
                hold_days = None

            position_info = {
                "shares": held_position["shares"],
                "avg_cost": avg_cost,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "unrealized_pnl_pct": pnl_pct,
                "dist_to_stop_pct": dist_to_stop,
                "dist_to_target_pct": dist_to_target,
                "hold_days": hold_days,
                "entry_reason": held_position.get("entry_reason")
            }

        result.update({
            "current_price": current_price,
            "price_1d_pct": price_1d_pct,
            "price_5d_pct": price_5d_pct,
            "volume_ratio": volume_ratio,
            "rsi_14": rsi,
            "above_20d_ma": above_20d_ma,
            "above_50d_ma": above_50d_ma,
            "sma_20": r(sma_20),
            "sma_50": r(sma_50),
            "52w_high": w52_high,
            "52w_low": w52_low,
            "dist_from_52w_high_pct": dist_from_52w_high,
            "market_cap": mc,
            "analyst_target": analyst_target,
            "analyst_upside_pct": analyst_upside,
            "short_float_pct": short_float,
            "inst_ownership_pct": inst_ownership,
            "beta": beta,
            "earnings_warning": earnings_warn,
            "recent_news": news,
            "position": position_info
        })
    except Exception as e:
        result["error"] = str(e)

    return result


def format_output(analyses: list, data: dict) -> dict:
    """Combine all analyses with portfolio context."""
    strategy = data["strategy"]
    cash = data["account"]["cash"]
    positions = data["positions"]
    open_slots = strategy["max_positions"] - len(positions)
    min_reserve = data["account"]["starting_cash"] * strategy.get("min_cash_reserve_pct", 0.15)
    deployable = max(0, round(cash - min_reserve, 2))
    max_per_position = round(cash * strategy["max_position_pct"], 2)

    # Split into held vs candidates
    held_tickers = {p["ticker"] for p in positions}
    current_pos_analyses = [a for a in analyses if a["ticker"] in held_tickers]
    candidate_analyses = [a for a in analyses if a["ticker"] not in held_tickers]

    # VIX risk flag
    risk_flags = []
    try:
        vix_t = yf.Ticker("^VIX")
        vix_hist = vix_t.history(period="2d")
        if not vix_hist.empty:
            vix_val = float(vix_hist["Close"].iloc[-1])
            if vix_val > 30:
                risk_flags.append(f"VIX at {vix_val:.1f} — HIGH VOLATILITY: reduce position sizes by 30%")
            elif vix_val > 22:
                risk_flags.append(f"VIX at {vix_val:.1f} — elevated volatility: be selective")
    except Exception:
        pass

    # Portfolio value
    perf = data.get("performance", {})
    portfolio_value = perf.get("portfolio_value") or cash

    return {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "portfolio_context": {
            "cash": cash,
            "total_value": portfolio_value,
            "open_positions": len(positions),
            "available_slots": open_slots,
            "deployable_cash": deployable,
            "max_per_position": max_per_position
        },
        "current_positions_analysis": current_pos_analyses,
        "candidates_analysis": candidate_analyses,
        "strategy_params": {
            "stop_loss_pct": strategy["stop_loss_pct"],
            "take_profit_pct": strategy["take_profit_pct"],
            "max_positions": strategy["max_positions"],
            "min_volume_surge": strategy["min_volume_surge"],
            "min_price_move_pct": strategy["min_price_move_pct"],
            "max_price_move_pct": strategy["max_price_move_pct"],
            "min_score": strategy.get("min_score", 60),
            "max_rsi_entry": strategy.get("max_rsi_entry", 72),
            "earnings_avoidance_days": strategy.get("earnings_avoidance_days", 10),
            "time_exit_days": strategy.get("time_exit_days", 14)
        },
        "risk_flags": risk_flags
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="+", help="Tickers to analyze")
    args = parser.parse_args()

    data = load_data()
    positions_map = {p["ticker"]: p for p in data["positions"]}

    analyses = []
    for ticker_sym in [t.upper() for t in args.tickers]:
        held = positions_map.get(ticker_sym)
        analysis = fetch_analysis(ticker_sym, held_position=held)
        analyses.append(analysis)

    output = format_output(analyses, data)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
