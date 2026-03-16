#!/usr/bin/env python3
"""
Feedback and learning engine — analyzes closed trades, extracts patterns, suggests strategy updates.
Usage: python3 learn.py [--min-closed N]
Outputs suggestions JSON to stdout. Does NOT auto-write to data.json.
Claude reviews and applies accepted lessons via portfolio.py --apply-lessons.
"""

import json
import sys
import argparse
from datetime import date
from collections import defaultdict

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


def extract_closed_trades(data: dict) -> list:
    """Pair BUY/SELL records into completed round-trips."""
    buys = {}
    sell_records = []

    for t in data["trades"]:
        if t["action"] == "BUY":
            buys[t["id"]] = t
        elif t["action"] == "SELL":
            sell_records.append(t)

    closed = []
    for sell in sell_records:
        buy_id = sell.get("buy_id")
        buy = buys.get(buy_id) if buy_id else None
        closed.append({
            "ticker": sell["ticker"],
            "outcome": sell.get("outcome", "UNKNOWN"),
            "realized_pnl": sell.get("realized_pnl", 0),
            "realized_pnl_pct": sell.get("realized_pnl_pct", 0),
            "hold_days": sell.get("hold_days", 0),
            "exit_reason": sell.get("exit_reason", ""),
            "entry_reason": sell.get("entry_reason") or (buy.get("reason") if buy else ""),
            "sell_date": sell.get("date", ""),
        })

    return closed


def hold_days_bucket(days: int) -> str:
    if days <= 3:
        return "1-3d"
    elif days <= 7:
        return "4-7d"
    elif days <= 14:
        return "8-14d"
    else:
        return "15+d"


def pattern_analysis(closed: list) -> dict:
    """Compute patterns across closed trades."""
    if not closed:
        return {}

    wins = [t for t in closed if t["outcome"] == "WIN"]
    losses = [t for t in closed if t["outcome"] == "LOSS"]
    total = len(closed)
    win_rate = round(len(wins) / total * 100, 1)

    avg_win_pct = round(sum(t["realized_pnl_pct"] for t in wins) / len(wins), 2) if wins else None
    avg_loss_pct = round(sum(t["realized_pnl_pct"] for t in losses) / len(losses), 2) if losses else None

    # Win rate by hold duration
    bucket_stats = defaultdict(lambda: {"wins": 0, "total": 0})
    for t in closed:
        b = hold_days_bucket(t["hold_days"])
        bucket_stats[b]["total"] += 1
        if t["outcome"] == "WIN":
            bucket_stats[b]["wins"] += 1

    win_rate_by_hold = {
        b: {
            "win_rate_pct": round(v["wins"] / v["total"] * 100, 1) if v["total"] > 0 else None,
            "count": v["total"]
        }
        for b, v in bucket_stats.items()
    }

    # Losses from stop-loss triggers
    stop_loss_exits = [t for t in losses if "stop" in t["exit_reason"].lower()]
    stop_loss_pct = round(len(stop_loss_exits) / len(losses) * 100, 1) if losses else 0

    # Check if losses are happening quickly (possible entry timing issue)
    fast_losses = [t for t in losses if t["hold_days"] <= 3]
    fast_loss_rate = round(len(fast_losses) / len(losses) * 100, 1) if losses else 0

    # Earnings-related keywords in exit reasons
    earnings_exits = [t for t in closed if "earning" in t["exit_reason"].lower() or "earning" in t["entry_reason"].lower()]

    return {
        "total_closed": total,
        "win_count": len(wins),
        "loss_count": len(losses),
        "overall_win_rate_pct": win_rate,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "win_rate_by_hold_days": win_rate_by_hold,
        "stop_loss_exit_pct": stop_loss_pct,
        "fast_loss_rate_pct": fast_loss_rate,  # losses within 3 days
        "earnings_related_trades": len(earnings_exits),
        "largest_win_pct": round(max((t["realized_pnl_pct"] for t in wins), default=0), 2),
        "largest_loss_pct": round(min((t["realized_pnl_pct"] for t in losses), default=0), 2),
    }


def generate_lessons(pattern: dict, closed: list, existing_lessons: list) -> list:
    """Rule-based lesson generation from pattern analysis."""
    lessons = []
    existing_texts = {l.get("lesson", "") for l in existing_lessons}

    def add_lesson(lesson, source_type, priority="MEDIUM"):
        if lesson not in existing_texts:
            lessons.append({"lesson": lesson, "source_type": source_type,
                            "priority": priority, "applied_to_strategy": False})

    # Lesson: fast losses suggest entries are bad (entering too late in move)
    if pattern.get("fast_loss_rate_pct", 0) > 50 and pattern.get("loss_count", 0) >= 2:
        add_lesson(
            "More than half of losses occur within 3 days — entries may be too late in the move. "
            "Raise volume surge threshold and require price momentum in earlier part of range.",
            "fast_losses", "HIGH"
        )

    # Lesson: stop loss too loose if avg loss is large
    avg_loss = pattern.get("avg_loss_pct")
    if avg_loss and avg_loss < -11:
        add_lesson(
            f"Average loss is {avg_loss:.1f}% — exceeding 10% stop loss target. "
            "Consider tightening stop loss to 8% or setting stops immediately after entry.",
            "large_avg_loss", "HIGH"
        )

    # Lesson: longer holds have better win rate — resist selling early
    wr_by_hold = pattern.get("win_rate_by_hold_days", {})
    short_wr = (wr_by_hold.get("1-3d") or {}).get("win_rate_pct", 0) or 0
    long_wr = (wr_by_hold.get("8-14d") or {}).get("win_rate_pct", 0) or 0
    if long_wr > short_wr + 20 and (wr_by_hold.get("8-14d") or {}).get("count", 0) >= 2:
        add_lesson(
            f"8-14 day holds show {long_wr:.0f}% win rate vs {short_wr:.0f}% for 1-3 day holds. "
            "Resist urge to sell winners early — let them run to the take-profit target.",
            "hold_duration_analysis", "MEDIUM"
        )

    # Lesson: overall win rate below 40% — tighten entry criteria
    overall_wr = pattern.get("overall_win_rate_pct", 100)
    if overall_wr < 40 and pattern.get("total_closed", 0) >= 5:
        add_lesson(
            f"Win rate is only {overall_wr:.0f}% over {pattern['total_closed']} trades. "
            "Raise minimum entry score from 60 to 70 and require volume ratio >= 2.5x.",
            "low_win_rate", "HIGH"
        )

    # Lesson: high earnings exit rate — reinforce the rule
    earnings_count = pattern.get("earnings_related_trades", 0)
    if earnings_count >= 2:
        add_lesson(
            f"{earnings_count} trades involved earnings proximity. "
            "Strictly enforce: never hold through earnings; exit at least 2 trading days before.",
            "earnings_risk", "HIGH"
        )

    # Lesson: win rate is good — suggest taking partial profits
    if overall_wr >= 65 and pattern.get("avg_win_pct", 0) and pattern["avg_win_pct"] < 15:
        add_lesson(
            f"Win rate {overall_wr:.0f}% is strong but avg win {pattern['avg_win_pct']:.1f}% is below take-profit target. "
            "Consider raising take-profit to 25% and holding winners longer.",
            "good_win_rate_small_wins", "MEDIUM"
        )

    return lessons


def suggest_strategy_updates(pattern: dict, current_strategy: dict) -> dict:
    """Suggest concrete strategy parameter changes based on patterns."""
    updates = {}
    notes_parts = []

    avg_loss = pattern.get("avg_loss_pct")
    overall_wr = pattern.get("overall_win_rate_pct", 100)
    fast_loss_rate = pattern.get("fast_loss_rate_pct", 0)

    # Tighten stop loss if losses are running large
    if avg_loss and avg_loss < -12:
        new_stop = max(0.06, round(current_strategy["stop_loss_pct"] - 0.02, 2))
        if new_stop < current_strategy["stop_loss_pct"]:
            updates["stop_loss_pct"] = new_stop
            notes_parts.append(f"stop_loss: {current_strategy['stop_loss_pct']} → {new_stop} (avg loss too large)")

    # Raise volume surge requirement if win rate is poor
    if overall_wr < 40 and pattern.get("total_closed", 0) >= 5:
        new_vol = min(3.0, round(current_strategy["min_volume_surge"] + 0.5, 1))
        if new_vol > current_strategy["min_volume_surge"]:
            updates["min_volume_surge"] = new_vol
            notes_parts.append(f"min_volume_surge: {current_strategy['min_volume_surge']} → {new_vol} (poor win rate)")

    # Raise min score if entries look poor (fast losses)
    if fast_loss_rate > 60:
        new_score = min(80, current_strategy.get("min_score", 60) + 10)
        if new_score > current_strategy.get("min_score", 60):
            updates["min_score"] = new_score
            notes_parts.append(f"min_score: {current_strategy.get('min_score', 60)} → {new_score} (too many fast losses)")

    # Raise take profit if winning trades are profitable
    avg_win = pattern.get("avg_win_pct", 0)
    if avg_win and avg_win >= 18 and overall_wr >= 55:
        new_tp = min(0.30, round(current_strategy["take_profit_pct"] + 0.05, 2))
        if new_tp > current_strategy["take_profit_pct"]:
            updates["take_profit_pct"] = new_tp
            notes_parts.append(f"take_profit: {current_strategy['take_profit_pct']} → {new_tp} (wins hitting target, let ride)")

    return {
        "updates": updates,
        "notes": "; ".join(notes_parts) if notes_parts else "No parameter changes suggested"
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-closed", type=int, default=3,
                        help="Minimum closed trades required to run analysis (default: 3)")
    args = parser.parse_args()

    data = load_data()
    closed = extract_closed_trades(data)

    if len(closed) < args.min_closed:
        print(json.dumps({
            "eligible": False,
            "reason": f"Only {len(closed)} closed trade(s) — need at least {args.min_closed}",
            "closed_trades_count": len(closed),
            "new_lessons": [],
            "strategy_suggestions": {},
            "summary": "Not enough trade history yet. Keep trading and run the learning loop after more trades close."
        }, indent=2))
        return

    pattern = pattern_analysis(closed)
    existing_lessons = data.get("lessons", [])
    new_lessons = generate_lessons(pattern, closed, existing_lessons)
    strategy_suggestions = suggest_strategy_updates(pattern, data["strategy"])

    summary_parts = []
    if new_lessons:
        summary_parts.append(f"{len(new_lessons)} new lesson(s) identified")
    if strategy_suggestions["updates"]:
        summary_parts.append(f"Strategy updates suggested: {strategy_suggestions['notes']}")
    if not summary_parts:
        summary_parts.append("No new lessons or changes needed — strategy is performing well")

    print(json.dumps({
        "eligible": True,
        "closed_trades_analyzed": len(closed),
        "pattern_analysis": pattern,
        "new_lessons": new_lessons,
        "strategy_suggestions": strategy_suggestions,
        "summary": " | ".join(summary_parts)
    }, indent=2))


if __name__ == "__main__":
    main()
