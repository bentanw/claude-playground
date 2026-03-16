#!/usr/bin/env python3
"""
Portfolio state manager for portfolio-trader skill.
Usage:
  python3 portfolio.py --update-prices
  python3 portfolio.py --add-position TICKER SHARES PRICE "REASON"
  python3 portfolio.py --close TICKER SELL_PRICE SHARES "REASON"
  python3 portfolio.py --add-watchlist TICKER "REASON" TARGET_ENTRY
  python3 portfolio.py --apply-lessons LESSONS_JSON_FILE
"""

import json
import os
import sys
import argparse
from datetime import datetime, timezone, date

import yfinance as yf

_DIR = __import__("os").environ.get("PORTFOLIO_DIR", "outputs/portfolio-trader")
CONFIG_PATH = f"{_DIR}/config.json"
DATA_PATH = f"{_DIR}/data.json"


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def save_config(config: dict) -> None:
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(config, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def load() -> dict:
    config = load_config()
    with open(DATA_PATH, "r") as f:
        runtime = json.load(f)
    # Merge config + runtime into a single working dict (same shape as before)
    runtime["account"] = {
        "starting_cash": config["account"]["starting_cash"],
        "target": config["account"]["target"],
        "currency": config["account"].get("currency", "USD"),
        "timeframe_start": config["account"].get("timeframe_start"),
        "timeframe_end": config["account"].get("timeframe_end"),
        "cash": runtime["cash"],
    }
    runtime["strategy"] = config["strategy"]
    return runtime


def save(data: dict) -> None:
    runtime = {
        "meta": data["meta"],
        "cash": data["account"]["cash"],
        "positions": data["positions"],
        "trades": data["trades"],
        "watchlist": data["watchlist"],
        "lessons": data["lessons"],
        "performance": data["performance"],
    }
    runtime["meta"]["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tmp = DATA_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(runtime, f, indent=2)
    os.replace(tmp, DATA_PATH)
    sync_snapshot(data)


def sync_snapshot(data: dict) -> None:
    """Write current account snapshot to config.json for quick reference."""
    try:
        config = load_config()
        config["snapshot"] = {
            "current_cash": data["account"]["cash"],
            "portfolio_value": data["performance"].get("portfolio_value", data["account"]["cash"]),
            "open_positions": len(data["positions"]),
            "last_synced": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        save_config(config)
    except Exception:
        pass  # snapshot sync is best-effort, never block a trade


# ── Price fetching ────────────────────────────────────────────────────────────

def fetch_live_prices(tickers: list) -> dict:
    """Batch fetch current prices. Returns {ticker: price}."""
    prices = {}
    if not tickers:
        return prices
    try:
        # yfinance batch download
        import yfinance as yf
        data = yf.download(tickers, period="2d", auto_adjust=True, progress=False)
        close = data["Close"] if "Close" in data else data
        if hasattr(close, "columns"):
            for t in tickers:
                if t in close.columns:
                    series = close[t].dropna()
                    if not series.empty:
                        prices[t] = round(float(series.iloc[-1]), 4)
        else:
            # Single ticker
            series = close.dropna()
            if not series.empty and tickers:
                prices[tickers[0]] = round(float(series.iloc[-1]), 4)
    except Exception:
        # Fallback: fetch one by one
        for t in tickers:
            try:
                ticker = yf.Ticker(t)
                hist = ticker.history(period="2d")
                if not hist.empty:
                    prices[t] = round(float(hist["Close"].iloc[-1]), 4)
            except Exception:
                pass
    return prices


# ── Position management ───────────────────────────────────────────────────────

def update_positions(data: dict) -> dict:
    """Inject live prices into open positions and compute P&L."""
    positions = data.get("positions", [])
    if not positions:
        data = recompute_performance(data, 0.0)
        return data

    tickers = [p["ticker"] for p in positions]
    prices = fetch_live_prices(tickers)

    total_position_value = 0.0
    for p in positions:
        t = p["ticker"]
        price = prices.get(t)
        if price is not None:
            p["current_price"] = price
            shares = p["shares"]
            avg_cost = p["avg_cost"]
            current_value = round(price * shares, 2)
            cost_basis = round(avg_cost * shares, 2)
            pnl = round(current_value - cost_basis, 2)
            pnl_pct = round((price - avg_cost) / avg_cost * 100, 2)
            p["current_value"] = current_value
            p["unrealized_pnl"] = pnl
            p["unrealized_pnl_pct"] = pnl_pct
            total_position_value += current_value
        else:
            p["current_price"] = None
            p["current_value"] = None
            p["unrealized_pnl"] = None
            p["unrealized_pnl_pct"] = None

    data = recompute_performance(data, total_position_value)
    return data


def open_position(data: dict, ticker: str, shares: float, buy_price: float, reason: str) -> dict:
    """Open a new position: deduct cash, add to positions, record BUY trade."""
    ticker = ticker.upper()
    shares = float(shares)
    buy_price = float(buy_price)
    cost = round(shares * buy_price, 2)

    if data["account"]["cash"] < cost:
        print(json.dumps({"error": f"Insufficient cash. Have ${data['account']['cash']:.2f}, need ${cost:.2f}"}))
        sys.exit(1)

    strategy = data["strategy"]
    stop_loss_price = round(buy_price * (1 - strategy["stop_loss_pct"]), 4)
    take_profit_price = round(buy_price * (1 + strategy["take_profit_pct"]), 4)

    # Generate trade ID
    trade_id = f"t{len(data['trades']) + 1:03d}"

    # Add position
    today = date.today().isoformat()
    position = {
        "ticker": ticker,
        "shares": shares,
        "avg_cost": buy_price,
        "entry_date": today,
        "entry_reason": reason,
        "stop_loss": stop_loss_price,
        "take_profit": take_profit_price,
        "current_price": buy_price,
        "current_value": cost,
        "unrealized_pnl": 0.0,
        "unrealized_pnl_pct": 0.0
    }
    data["positions"].append(position)

    # Record BUY trade
    data["trades"].append({
        "id": trade_id,
        "ticker": ticker,
        "action": "BUY",
        "shares": shares,
        "price": buy_price,
        "date": today,
        "cost_basis": cost,
        "reason": reason
    })

    # Deduct cash
    data["account"]["cash"] = round(data["account"]["cash"] - cost, 2)
    data = recompute_performance(data)
    return data


def close_position(data: dict, ticker: str, sell_price: float, shares: float, exit_reason: str) -> dict:
    """Close a position: remove from positions, record SELL trade, update cash."""
    ticker = ticker.upper()
    sell_price = float(sell_price)
    shares = float(shares)

    # Find position
    pos_idx = None
    for i, p in enumerate(data["positions"]):
        if p["ticker"] == ticker:
            pos_idx = i
            break

    if pos_idx is None:
        print(json.dumps({"error": f"No open position found for {ticker}"}))
        sys.exit(1)

    pos = data["positions"][pos_idx]
    avg_cost = pos["avg_cost"]
    entry_date = pos["entry_date"]
    entry_reason = pos["entry_reason"]

    proceeds = round(sell_price * shares, 2)
    cost_basis = round(avg_cost * shares, 2)
    realized_pnl = round(proceeds - cost_basis, 2)
    realized_pnl_pct = round((sell_price - avg_cost) / avg_cost * 100, 2)

    # Calculate hold days
    try:
        entry_dt = date.fromisoformat(entry_date)
        hold_days = (date.today() - entry_dt).days
    except Exception:
        hold_days = 0

    outcome = "WIN" if realized_pnl > 0 else ("LOSS" if realized_pnl < 0 else "BREAKEVEN")

    # Find matching BUY trade ID
    buy_id = None
    for t in reversed(data["trades"]):
        if t["ticker"] == ticker and t["action"] == "BUY":
            buy_id = t["id"]
            break

    sell_id = f"t{len(data['trades']) + 1:03d}"

    data["trades"].append({
        "id": sell_id,
        "buy_id": buy_id,
        "ticker": ticker,
        "action": "SELL",
        "shares": shares,
        "price": sell_price,
        "date": date.today().isoformat(),
        "proceeds": proceeds,
        "cost_basis": cost_basis,
        "realized_pnl": realized_pnl,
        "realized_pnl_pct": realized_pnl_pct,
        "hold_days": hold_days,
        "entry_reason": entry_reason,
        "exit_reason": exit_reason,
        "outcome": outcome,
        "lessons": ""
    })

    # Remove position (handle partial closes: remove if all shares sold)
    remaining = pos["shares"] - shares
    if remaining <= 0.001:
        data["positions"].pop(pos_idx)
    else:
        data["positions"][pos_idx]["shares"] = remaining
        data["positions"][pos_idx]["avg_cost"] = avg_cost  # unchanged for partial

    # Add cash back
    data["account"]["cash"] = round(data["account"]["cash"] + proceeds, 2)
    data = recompute_performance(data)
    return data


def add_watchlist(data: dict, ticker: str, reason: str, target_entry: float) -> dict:
    ticker = ticker.upper()
    # Remove existing entry for same ticker
    data["watchlist"] = [w for w in data["watchlist"] if w["ticker"] != ticker]
    data["watchlist"].append({
        "ticker": ticker,
        "added_date": date.today().isoformat(),
        "reason": reason,
        "target_entry": float(target_entry) if target_entry else None,
        "interest_level": "MEDIUM"
    })
    return data


def apply_lessons(data: dict, lessons_file: str) -> dict:
    with open(lessons_file, "r") as f:
        payload = json.load(f)

    new_lessons = payload.get("accepted_lessons", [])
    strategy_updates = payload.get("strategy_updates", {})

    today = date.today().isoformat()
    for lesson in new_lessons:
        lesson["date"] = today
        data["lessons"].append(lesson)

    if strategy_updates:
        data["strategy"].update(strategy_updates)
        data["strategy"]["last_adjusted"] = today
        data["strategy"]["adjustment_notes"] = payload.get("adjustment_notes", "Updated by learning loop")
        # Write strategy updates back to config.json so they persist
        config = load_config()
        config["strategy"].update(strategy_updates)
        config["strategy"]["last_adjusted"] = today
        config["strategy"]["adjustment_notes"] = payload.get("adjustment_notes", "Updated by learning loop")
        save_config(config)

    # Append accepted lessons to notes/lessons.md for persistent context
    if new_lessons:
        notes_path = os.path.join(_DIR, "notes", "lessons.md")
        if os.path.exists(notes_path):
            with open(notes_path, "a") as f:
                for lesson in new_lessons:
                    priority = lesson.get("priority", "MEDIUM")
                    source = lesson.get("source_type", "")
                    text = lesson.get("lesson", "")
                    f.write(f"\n## [{today}] [{priority}] {source}\n{text}\n")

    return data


# ── Performance ───────────────────────────────────────────────────────────────

def recompute_performance(data: dict, total_position_value: float = None) -> dict:
    """Recompute all performance metrics from trade history."""
    closed = [t for t in data["trades"] if t["action"] == "SELL"]

    wins = [t for t in closed if t.get("outcome") == "WIN"]
    losses = [t for t in closed if t.get("outcome") == "LOSS"]

    total = len(closed)
    win_count = len(wins)
    loss_count = len(losses)

    win_rate = round(win_count / total * 100, 1) if total > 0 else None
    avg_win = round(sum(t["realized_pnl_pct"] for t in wins) / win_count, 2) if wins else None
    avg_loss = round(sum(t["realized_pnl_pct"] for t in losses) / loss_count, 2) if losses else None
    largest_win = round(max((t["realized_pnl_pct"] for t in wins), default=None), 2) if wins else None
    largest_loss = round(min((t["realized_pnl_pct"] for t in losses), default=None), 2) if losses else None
    total_realized = round(sum(t["realized_pnl"] for t in closed), 2)

    avg_hold_win = round(sum(t.get("hold_days", 0) for t in wins) / win_count, 1) if wins else None
    avg_hold_loss = round(sum(t.get("hold_days", 0) for t in losses) / loss_count, 1) if losses else None

    # Portfolio value
    if total_position_value is None:
        total_position_value = sum(
            p.get("current_value") or (p["shares"] * p["avg_cost"])
            for p in data["positions"]
        )
    portfolio_value = round(data["account"]["cash"] + total_position_value, 2)
    starting = data["account"]["starting_cash"]
    vs_start_pct = round((portfolio_value - starting) / starting * 100, 2) if starting else None

    data["performance"] = {
        "total_trades": total,
        "winning_trades": win_count,
        "losing_trades": loss_count,
        "win_rate_pct": win_rate,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "largest_win_pct": largest_win,
        "largest_loss_pct": largest_loss,
        "total_realized_pnl": total_realized,
        "portfolio_value": portfolio_value,
        "portfolio_value_vs_start_pct": vs_start_pct,
        "avg_hold_days_winners": avg_hold_win,
        "avg_hold_days_losers": avg_hold_loss
    }
    return data


# ── Summary output ────────────────────────────────────────────────────────────

def summary_json(data: dict) -> dict:
    """Build compact summary dict for Claude to read."""
    strategy = data["strategy"]
    perf = data["performance"]

    # Flag stop-loss and take-profit triggers
    triggers = []
    for p in data["positions"]:
        pnl_pct = p.get("unrealized_pnl_pct")
        if pnl_pct is None:
            continue
        if pnl_pct <= -(strategy["stop_loss_pct"] * 100):
            triggers.append({"ticker": p["ticker"], "trigger": "STOP_LOSS", "pnl_pct": pnl_pct})
        elif pnl_pct >= (strategy["take_profit_pct"] * 100):
            triggers.append({"ticker": p["ticker"], "trigger": "TAKE_PROFIT", "pnl_pct": pnl_pct})

    # Check time-exit (positions held too long with small gain)
    for p in data["positions"]:
        try:
            entry_dt = date.fromisoformat(p["entry_date"])
            hold_days = (date.today() - entry_dt).days
            pnl_pct = p.get("unrealized_pnl_pct") or 0
            if hold_days >= strategy["time_exit_days"] and abs(pnl_pct) < 5:
                triggers.append({"ticker": p["ticker"], "trigger": "TIME_EXIT", "hold_days": hold_days, "pnl_pct": pnl_pct})
        except Exception:
            pass

    open_slots = strategy["max_positions"] - len(data["positions"])
    cash = data["account"]["cash"]
    max_per_position = round(cash * strategy["max_position_pct"], 2)
    min_reserve = round(data["account"].get("starting_cash", 1000) * strategy.get("min_cash_reserve_pct", 0.15), 2)
    deployable = max(0, round(cash - min_reserve, 2))

    # Timeframe progress
    timeframe = {}
    try:
        tf_start = data["account"].get("timeframe_start")
        tf_end = data["account"].get("timeframe_end")
        if tf_start and tf_end:
            start_dt = date.fromisoformat(tf_start)
            end_dt = date.fromisoformat(tf_end)
            today_dt = date.today()
            total_days = (end_dt - start_dt).days
            elapsed_days = max(0, (today_dt - start_dt).days)
            remaining_days = max(0, (end_dt - today_dt).days)
            pct_time_elapsed = round(elapsed_days / total_days * 100, 1) if total_days > 0 else None

            portfolio_value = perf.get("portfolio_value", cash)
            target = data["account"]["target"]
            starting = data["account"]["starting_cash"]
            pct_to_target = round((portfolio_value - starting) / (target - starting) * 100, 1) if target != starting else None
            gap = (pct_to_target or 0) - (pct_time_elapsed or 0)
            if pct_to_target is None:
                pace_status = "NO_DATA"
            elif gap >= 10:
                pace_status = "AHEAD"
            elif gap >= -10:
                pace_status = "ON_PACE"
            elif remaining_days > total_days * 0.3:
                pace_status = "BEHIND"
            else:
                pace_status = "CRITICAL"
            on_pace = pace_status in ("AHEAD", "ON_PACE")

            # Required growth rate to hit target from here
            if remaining_days > 0 and portfolio_value < target:
                required_total_pct = round((target / portfolio_value - 1) * 100, 1)
            else:
                required_total_pct = 0.0

            timeframe = {
                "start": tf_start,
                "end": tf_end,
                "total_days": total_days,
                "elapsed_days": elapsed_days,
                "remaining_days": remaining_days,
                "pct_time_elapsed": pct_time_elapsed,
                "pct_to_target": pct_to_target,
                "pace_status": pace_status,
                "on_pace": on_pace,
                "required_gain_to_target_pct": required_total_pct,
            }
    except Exception:
        pass

    return {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "account": {
            "cash": cash,
            "target": data["account"]["target"],
            "starting_cash": data["account"]["starting_cash"],
            "timeframe_start": data["account"].get("timeframe_start"),
            "timeframe_end": data["account"].get("timeframe_end"),
        },
        "portfolio_value": perf.get("portfolio_value"),
        "vs_start_pct": perf.get("portfolio_value_vs_start_pct"),
        "open_positions": len(data["positions"]),
        "available_slots": open_slots,
        "deployable_cash": deployable,
        "max_per_position": max_per_position,
        "positions": data["positions"],
        "watchlist": data["watchlist"],
        "performance": perf,
        "timeframe": timeframe,
        "strategy": strategy,
        "triggers": triggers,
        "lessons_count": len(data["lessons"])
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--update-prices", action="store_true")
    parser.add_argument("--add-position", nargs=4, metavar=("TICKER", "SHARES", "PRICE", "REASON"))
    parser.add_argument("--close", nargs=4, metavar=("TICKER", "SELL_PRICE", "SHARES", "REASON"))
    parser.add_argument("--add-watchlist", nargs=3, metavar=("TICKER", "REASON", "TARGET_ENTRY"))
    parser.add_argument("--apply-lessons", metavar="LESSONS_JSON_FILE")
    args = parser.parse_args()

    data = load()

    if args.update_prices:
        data = update_positions(data)
        save(data)
        print(json.dumps(summary_json(data), indent=2))

    elif args.add_position:
        ticker, shares, price, reason = args.add_position
        data = open_position(data, ticker, float(shares), float(price), reason)
        save(data)
        print(json.dumps({"status": "ok", "action": "BUY", "ticker": ticker.upper(),
                          "shares": float(shares), "price": float(price),
                          "cash_remaining": data["account"]["cash"]}, indent=2))

    elif args.close:
        ticker, sell_price, shares, reason = args.close
        data = close_position(data, ticker, float(sell_price), float(shares), reason)
        save(data)
        # Find the sell trade just added
        sell_trade = next((t for t in reversed(data["trades"]) if t["action"] == "SELL" and t["ticker"] == ticker.upper()), {})
        print(json.dumps({"status": "ok", "action": "SELL", "ticker": ticker.upper(),
                          "realized_pnl": sell_trade.get("realized_pnl"),
                          "realized_pnl_pct": sell_trade.get("realized_pnl_pct"),
                          "outcome": sell_trade.get("outcome"),
                          "cash_now": data["account"]["cash"]}, indent=2))

    elif args.add_watchlist:
        ticker, reason, target_entry = args.add_watchlist
        data = add_watchlist(data, ticker, reason, target_entry)
        save(data)
        print(json.dumps({"status": "ok", "action": "WATCHLIST", "ticker": ticker.upper()}, indent=2))

    elif args.apply_lessons:
        data = apply_lessons(data, args.apply_lessons)
        save(data)
        print(json.dumps({"status": "ok", "action": "APPLY_LESSONS",
                          "lessons_total": len(data["lessons"])}, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
