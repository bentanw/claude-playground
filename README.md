## Claude playground

Building this for my daily needs. All outputs will be genereated inside of `outputs/` file

## Usage

- `/stock-researcher`
  - To use, simply start `claude` in terminal
  - Describe your stock, example usage
    - `/stock-research PLTR avg buy is $40, I have 50 shares, output in Chinese`
- `/portfolio-trader`
  - Setup (one time)
    - Edit outputs/portfolio-trader/config.json to set your account:
    - Change starting_cash to whatever you're starting with
    - Change target to your goal
    - Add/remove tickers from scan_universe if you want
  - Running it
    - Just type in the chat: `/portfolio-trader`, Claude will:
      - Fetch live prices for your positions
      - Scan the universe for momentum candidates
      - Deep-analyze top candidates + current holdings
      - Show you a full report with SELL / BUY / WATCH recommendations
      - Ask: "Confirm trades — or enter your actual fill prices"
      - You say yes (or give different prices) → Claude records everything to data.json
  - `/portfolio-trader status`   # read-only snapshot, no trade recommendations
  - `/portfolio-trader learn`    # force the learning loop to run (needs 3+ closed trades)
  - Typical flow
    - Morning (~10 AM ET): Run /portfolio-trader → review recommendations → confirm trades with
    your actual fill prices
    - Afternoon (~1 PM ET): Run it again → check if any stops/targets were hit → act on them
    - When a position closes (stop loss or take profit hit): the learning loop runs automatically
    - if you have 3+ closed trades, shows you patterns, and asks if you want to tighten/loosen any
    parameters in config.json
    - Never touch:
      - data.json — Claude writes to it every time you confirm trades. Your trade history, positions, and P&L all live there automatically.

