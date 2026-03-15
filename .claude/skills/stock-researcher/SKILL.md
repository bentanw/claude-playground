---
name: stock-researcher
description: "Warren Buffett-style stock research. Drills top-down: macro → sector → company overview → competitive position → fundamentals → news → verdict with buy/hold/sell recommendation. Use when the user provides a stock ticker (or multiple tickers), optionally with share count and average cost. Also handles image input — parse the image to extract ticker, shares, cost, etc."
---

# Stock Researcher

Perform a full Warren Buffett-style analysis on a stock. Be brutally objective. No bias. No softening.

## Arguments

```
TICKER [shares_held] [avg_cost] [lang]
```

- `TICKER` — stock ticker symbol (required); may be multiple tickers (see Parallel Batching below)
- `shares_held` — number of shares you own (optional)
- `avg_cost` — your average cost per share (optional, requires shares_held)
- `lang` — output language: `en` (English, default) or `zh` (Mandarin Chinese)

Examples:
- `AAPL` — analysis only, English
- `AAPL 150` — analysis + position recommendation for 150 shares
- `AAPL 150 182.50` — analysis + position rec + P&L based on avg cost of $182.50/share
- `AAPL zh` — full analysis in Mandarin Chinese
- `AAPL 150 182.50 zh` — full analysis + position P&L in Mandarin Chinese
- `AAPL TSLA NVDA` — parallel analysis of three tickers (see Parallel Batching)
- `[image]` — parse image to extract ticker/shares/cost, then analyse (see Image Input)

**Language rules:**
- If `lang=zh`, write the **entire report in Mandarin Chinese** — every section header, all body text, all table content (metric names, thresholds, verdicts), all bullet points, the position recommendation, and the objectivity disclaimer. No English except the ticker symbol itself and numeric values.
- If `lang=en` or lang not specified, write in English (default).
- Pass `--lang zh` to `pdf_report.py` when generating the PDF so Chinese fonts are used.

---

## ⚠️ Data Integrity Rule

**Base ALL analysis exclusively on:**
- The JSON data returned by `research.py` (live market data)
- Your own reasoning applied to that data
- Known public facts about the company's business model and products

**Never base analysis on:**
- External analyst price targets or recommendations (do not quote them as gospel — they are listed in the data for context only)
- Projected reports, consensus estimates from third parties, or external research notes
- Speculative forecasts not grounded in the actual data returned

The analysis must reflect current reality, not what someone else predicted.

---

## Step 0 — Image Input (if applicable)

If the user provides an **image** (file path or inline image) instead of text arguments:

1. Use the **Read tool** to open and view the image.
2. Extract every relevant field you can see: ticker symbol, current price, shares held, average cost, P&L, date, etc. Missing fields are fine — just use what is visible.
3. Proceed with the analysis using the extracted data exactly as if the user had typed the arguments.

Common image types to handle: brokerage position screenshots, portfolio summaries, stock charts with annotations, watchlist exports.

---

## Step 0b — Parallel Batching (multiple tickers)

If the input contains **more than one ticker** (e.g. `AAPL TSLA NVDA` or `AAPL, TSLA, NVDA`):

1. **Do NOT analyse them sequentially.** Launch one `general-purpose` Agent subagent per ticker **in parallel** using the Agent tool (multiple Agent tool calls in a single message).
2. Each subagent receives a self-contained prompt with:
   - The single ticker it is responsible for
   - Any shares/avg_cost/lang arguments that apply to that ticker
   - The full instruction to run the complete stock-researcher workflow (fetch data, write report, generate PDF) for that ticker
   - The project root path: `/Users/bentan/Codebase/claude-playground`
3. Wait for all subagents to complete, then summarise results to the user (one line per ticker: company name, rating, stance, PDF path).

---

## Step 1 — Fetch Data

All commands run from the **project root** using the shared venv.

```bash
venv/bin/python3 .claude/skills/stock-researcher/scripts/research.py <TICKER>
```

If the venv doesn't exist yet, set it up first:
```bash
python3.11 -m venv venv
venv/bin/pip3 install yfinance reportlab -q
```

Parse the JSON output carefully. Every field matters.

---

## Step 2 — Build the Report Content

Compose the full report as markdown text. You will pipe this directly into the PDF generator — **do not write a `.md` file to `outputs/`**.

Use this exact report structure:

---

```
# [COMPANY NAME] ($TICKER) — Stock Research Report
*Analysis Date: YYYY-MM-DD | Data as of: [as_of from JSON]*

---

## 1. What Does This Company Do?

Write this section for a non-technical, non-finance audience. No jargon.

**In plain English**: [1–2 sentence summary of what the company does, as if explaining to a family member]

**The Problem They Solve**: [What pain point or need does this company address? Why does it exist?]

**Their Products / Services**:
- [Product/service 1]: [One sentence on what it is and who uses it]
- [Product/service 2]: [Same]
- [Add as many as relevant — be thorough but concise]

**Who Are Their Customers**: [Who pays them? Consumers? Businesses? Governments? What size companies? What industries?]

**Why It Matters**: [In 1–2 sentences, why is this business relevant right now — is there a macro or technology shift driving demand for what they do?]

---

## 2. Global Macro Environment

- S&P 500 30d: X% | Nasdaq 30d: X%
- VIX: X (fear level: low <15 / moderate 15–25 / elevated 25–35 / extreme >35)
- 10Y Treasury Yield: X% (rate regime: rising/falling/stable)
- US Dollar (DXY): X%

**Macro Regime**: [1–2 sentences. Is this risk-on or risk-off? Tightening or easing cycle? What does this mean for equities broadly?]

---

## 3. Sector Analysis — [SECTOR]

- Sector ETF ([ETF]): [3-month %] vs SPY: [3-month %]
- [TICKER] 30-day performance: X%

**Sector Read**: [Is the sector outperforming or underperforming the market? Identify structural tailwinds or headwinds (regulation, rates, AI disruption, commodity cycle, etc.)]

---

## 4. Competitive Position

- **Moat Type**: [Brand / Network Effects / Switching Costs / Cost Advantage / None]
- **Moat Strength**: [Strong / Moderate / Weak / None]
- **Competitive Assessment**: [2–3 sentences. Who are the main competitors? Is market share growing or shrinking? What is the primary threat to this company's position? Be specific — no vague platitudes.]

---

## 5. Company Fundamentals — Buffett Checklist

| Metric | Value | Threshold | Verdict |
|--------|-------|-----------|---------|
| ROE | X% | >15% | ✅ PASS / ❌ FAIL |
| Debt/Equity | X | <0.5 preferred | ✅ PASS / ⚠️ ELEVATED / ❌ HIGH |
| Net Margin | X% | >10% preferred | ✅ / ⚠️ / ❌ |
| Gross Margin | X% | >40% for wide moat | ✅ / ⚠️ / ❌ |
| Free Cash Flow | $X | Positive + growing | ✅ / ❌ |
| Revenue Growth YoY | X% | >5% preferred | ✅ / ⚠️ / ❌ |
| P/E (Trailing) | X | Context-dependent | cheap/fair/expensive |
| Forward P/E | X | vs. sector avg | cheap/fair/expensive |
| PEG Ratio | X | <1.0 undervalued | ✅ / ⚠️ / ❌ |
| EV/EBITDA | X | <15 reasonable | cheap/fair/expensive |
| Current Ratio | X | >1.5 healthy | ✅ / ⚠️ / ❌ |
| Beta | X | context | low/medium/high risk |

**Fundamentals Summary**: [3–4 blunt sentences based purely on the data above. Where does this company excel? Where does it fail? If a metric is bad, say it's bad. Don't hedge.]

---

## 6. News — Past 30 Days ([N] articles)

[List ALL news items from the JSON:]
- **[DATE]** — [TITLE] *(source)*

**News Assessment**: [What is the dominant narrative? Flag red flags in bold — earnings misses, lawsuits, executive departures, regulatory action, guidance cuts. If zero red flags, say so explicitly. Do NOT cite external analyst opinions as analysis — only report facts from the headlines.]

---

## 7. Catalysts (Next 6–12 Months)

Identify upcoming events that could materially move the stock — based on what is known from the data and news, not from external forecasts:

- Earnings dates
- Product launches
- Regulatory approvals / rulings
- Major contracts or partnerships
- M&A activity
- Buybacks / dividends
- Leadership changes

Label each: **BULLISH** / **BEARISH** / **NEUTRAL**

---

## 8. Verdict

**Overall Rating: X/10**
*(1–3 = Strong Sell | 4 = Sell | 5 = Hold | 6–7 = Buy | 8–10 = Strong Buy)*

**Stance: BULLISH / NEUTRAL / BEARISH**

**Bull Case** (2 sentences max): [What has to go right for this stock to outperform?]

**Bear Case** (2 sentences max): [What is the most likely way this investment loses money?]

---

[ONLY IF shares_held was provided:]

## 9. Your Position

**You hold [shares_held] shares**
**Current value**: $[shares_held × current_price]

[ONLY IF avg_cost was also provided:]
**Avg cost**: $[avg_cost]/share
**Total cost basis**: $[shares_held × avg_cost]
**Unrealized P&L**: $[current_value − cost_basis] ([pct]%)
**Current price vs avg cost**: [above/below] by $X ([pct]%)

**Recommendation: BUY MORE / HOLD / SELL**

[2–3 blunt sentences. Make a direct recommendation based purely on the data — not on the user's cost basis, emotions, or holding period. If the data says sell, say sell.]

**Suggested action**: [One concrete sentence with a specific price level.]

---

**Key Risks:**
1. [Specific risk #1]
2. [Specific risk #2]
3. [Specific risk #3]

---

> ⚠️ **Objectivity Notice**: This analysis is based solely on current market data — not on external analyst projections or third-party research reports. It carries zero bias toward any existing position. If the data is unflattering, it says so plainly. *This is not financial advice.*
```

---

## Step 3 — Export as PDF (no .md file left behind)

Write the markdown content to a **temporary file** at `/tmp/stock-<TICKER>-<YYYY-MM-DD>.md`, generate the PDF, then delete the temp file. The only permanent output is the `.pdf`.

```bash
# 1. Write report to temp file (use the Write tool)
#    Path: /tmp/stock-<TICKER>-<YYYY-MM-DD>.md

# 2. Generate PDF
venv/bin/python3 .claude/skills/stock-researcher/scripts/pdf_report.py \
  /tmp/stock-<TICKER>-<YYYY-MM-DD>.md \
  outputs/stock-researcher/stock-<TICKER>-<YYYY-MM-DD>.pdf \
  [--lang zh]

# 3. Delete the temp file
rm /tmp/stock-<TICKER>-<YYYY-MM-DD>.md
```

Pass `--lang zh` when the report is in Mandarin Chinese so the PDF uses Chinese-compatible fonts.

The PDF uses `reportlab` with:
- Clean title header with company name, ticker, and date
- Section headings clearly differentiated from body text
- Fundamentals table rendered as an actual table
- News list as a bullet list
- Body: 10pt, headings: 13pt, title: 18pt
- Margins: 1 inch all sides
- Page numbers in footer

---

## Tone Directive

**Be harsh. Be blunt. Be a truth-teller.**

- If ROE is 4%, say "ROE of 4% is well below the 15% threshold — this company is not generating adequate returns on shareholder equity."
- If the stock is expensive, say it's expensive and explain at what valuation it would become interesting.
- If the news is bad, call it bad news.
- Never say "it depends" without immediately saying what it depends on and what that implies.
- Never use filler phrases like "it's worth noting" or "investors should consider."
- The user can handle the truth. Give it to them.
- **Never reference external analyst forecasts as the basis for a verdict.** Use the data. Form your own view.

**Do not let the user's share count or cost basis influence your verdict.** A person holding 10,000 shares at a loss who should sell gets the same answer as someone holding 1 share at a gain.
