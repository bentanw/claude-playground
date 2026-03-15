#!/usr/bin/env python3
"""
Stock research data fetcher.
Usage: python3 research.py <TICKER>
Outputs JSON to stdout.
"""

import json
import sys
import time
from datetime import datetime, timezone

import yfinance as yf

# ── Sector → ETF mapping ──────────────────────────────────────────────────────
SECTOR_ETF = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Basic Materials": "XLB",
    "Communication Services": "XLC",
}

def pct_change_30d(ticker_sym: str) -> dict:
    """Return current price and 30-day % change for a symbol."""
    try:
        t = yf.Ticker(ticker_sym)
        hist = t.history(period="35d")
        if len(hist) < 2:
            return {"symbol": ticker_sym, "current": None, "pct_30d": None}
        current = round(float(hist["Close"].iloc[-1]), 4)
        start   = round(float(hist["Close"].iloc[0]),  4)
        pct     = round((current - start) / start * 100, 2)
        return {"symbol": ticker_sym, "current": current, "pct_30d": pct}
    except Exception as e:
        return {"symbol": ticker_sym, "current": None, "pct_30d": None, "error": str(e)}

def sector_vs_spy(etf_sym: str) -> dict:
    """Return 3-month % change for sector ETF and SPY."""
    result = {}
    for sym in [etf_sym, "SPY"]:
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="95d")
            if len(hist) < 2:
                result[sym] = None
                continue
            c = float(hist["Close"].iloc[-1])
            s = float(hist["Close"].iloc[0])
            result[sym] = round((c - s) / s * 100, 2)
        except Exception:
            result[sym] = None
    return result

def safe_get(d: dict, *keys):
    """Safely get nested dict value."""
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d

def fetch_news_30d(ticker_obj) -> list:
    """Return news items from the past 30 days. Handles both old and new yfinance formats."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=timezone.utc)
    from datetime import timedelta
    cutoff = cutoff - timedelta(days=30)
    results = []
    try:
        raw = ticker_obj.news or []
        for item in raw:
            # New yfinance format: nested under item["content"]
            content = item.get("content") or item
            title     = content.get("title") or item.get("title", "")
            publisher = (content.get("provider") or {}).get("displayName") or item.get("publisher", "")
            url       = ((content.get("canonicalUrl") or content.get("clickThroughUrl")) or {}).get("url") or item.get("link", "")

            # Date: try ISO pubDate first, then legacy providerPublishTime
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

            if pub_dt and pub_dt >= cutoff:
                results.append({
                    "title":     title,
                    "publisher": publisher,
                    "date":      pub_dt.strftime("%Y-%m-%d"),
                    "url":       url,
                })
    except Exception:
        pass
    return sorted(results, key=lambda x: x["date"], reverse=True)

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: research.py <TICKER>"}))
        sys.exit(1)

    ticker_sym = sys.argv[1].upper().strip()
    ticker     = yf.Ticker(ticker_sym)

    # ── company info ──────────────────────────────────────────────────────────
    info = {}
    try:
        info = ticker.info or {}
    except Exception:
        pass

    company_name = info.get("longName") or info.get("shortName") or ticker_sym
    sector       = info.get("sector", "Unknown")
    industry     = info.get("industry", "Unknown")
    sector_etf   = SECTOR_ETF.get(sector, "SPY")

    # ── macro ─────────────────────────────────────────────────────────────────
    macro_syms = ["^GSPC", "^IXIC", "^VIX", "^TNX", "DX-Y.NYB"]
    macro = [pct_change_30d(s) for s in macro_syms]

    # ── sector ────────────────────────────────────────────────────────────────
    sec_perf = sector_vs_spy(sector_etf)

    # ── stock 30d ─────────────────────────────────────────────────────────────
    stock_30d = pct_change_30d(ticker_sym)

    # ── fundamentals ─────────────────────────────────────────────────────────
    def r(v, decimals=2):
        try:
            return round(float(v), decimals) if v is not None else None
        except (TypeError, ValueError):
            return None

    # Free cash flow from cashflow statement
    fcf = None
    try:
        cf = ticker.cashflow
        if cf is not None and not cf.empty:
            op_cf  = cf.loc["Operating Cash Flow"].iloc[0]  if "Operating Cash Flow"  in cf.index else 0
            capex  = cf.loc["Capital Expenditure"].iloc[0]  if "Capital Expenditure"  in cf.index else 0
            fcf    = r(op_cf + capex, 0)   # capex is already negative
    except Exception:
        pass

    # Revenue YoY growth
    rev_growth = None
    try:
        fin = ticker.financials
        if fin is not None and not fin.empty and "Total Revenue" in fin.index:
            rev = fin.loc["Total Revenue"]
            if len(rev) >= 2:
                r0, r1 = float(rev.iloc[0]), float(rev.iloc[1])
                rev_growth = r((r0 - r1) / abs(r1) * 100) if r1 != 0 else None
    except Exception:
        pass

    fundamentals = {
        "current_price":    r(info.get("currentPrice") or info.get("regularMarketPrice")),
        "market_cap":       info.get("marketCap"),
        "52w_high":         r(info.get("fiftyTwoWeekHigh")),
        "52w_low":          r(info.get("fiftyTwoWeekLow")),
        "pe_trailing":      r(info.get("trailingPE")),
        "pe_forward":       r(info.get("forwardPE")),
        "pb":               r(info.get("priceToBook")),
        "ev_ebitda":        r(info.get("enterpriseToEbitda")),
        "roe":              r(info.get("returnOnEquity"), 4),       # as decimal
        "roa":              r(info.get("returnOnAssets"), 4),
        "debt_to_equity":   r(info.get("debtToEquity")),           # as ratio
        "current_ratio":    r(info.get("currentRatio")),
        "net_margin":       r(info.get("profitMargins"), 4),
        "gross_margin":     r(info.get("grossMargins"), 4),
        "free_cash_flow":   fcf,
        "revenue_growth_yoy_pct": rev_growth,
        "dividend_yield":   r(info.get("dividendYield"), 4),
        "beta":             r(info.get("beta")),
        "shares_outstanding": info.get("sharesOutstanding"),
        "peg_ratio":        r(info.get("pegRatio")),
        "analyst_target":   r(info.get("targetMeanPrice")),
        "analyst_recommendation": info.get("recommendationMean"),
    }

    # ── news (past 30 days) ───────────────────────────────────────────────────
    news = fetch_news_30d(ticker)

    # ── assemble output ───────────────────────────────────────────────────────
    output = {
        "ticker":       ticker_sym,
        "company":      company_name,
        "sector":       sector,
        "industry":     industry,
        "sector_etf":   sector_etf,
        "as_of":        datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "macro":        macro,
        "sector_performance_3m": {
            "sector_etf_sym": sector_etf,
            "sector_etf_pct": sec_perf.get(sector_etf),
            "spy_pct":        sec_perf.get("SPY"),
        },
        "stock_30d_pct":    stock_30d.get("pct_30d"),
        "fundamentals":     fundamentals,
        "news_30d":         news,
        "news_count_30d":   len(news),
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
