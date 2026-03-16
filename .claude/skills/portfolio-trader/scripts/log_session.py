#!/usr/bin/env python3
"""
Session logger for portfolio-trader.
Appends the session report to a daily markdown log and regenerates the day's PDF.

Multiple sessions per day are appended under numbered headers.

Usage:
  echo "markdown content" | python3 log_session.py [--mode LIVE|MOCK]
  python3 log_session.py --file /tmp/session.md [--mode LIVE|MOCK]

Respects PORTFOLIO_DIR env var (default: outputs/portfolio-trader).
"""

import sys
import os
import subprocess
import argparse
from datetime import datetime

_DIR = os.environ.get("PORTFOLIO_DIR", "outputs/portfolio-trader")
LOG_DIR = os.path.join(_DIR, "log")
PDF_SCRIPT = ".claude/skills/stock-researcher/scripts/pdf_report.py"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="Path to session markdown file (default: read stdin)")
    parser.add_argument("--mode", default="", help="Session mode tag e.g. MOCK, LIVE")
    args = parser.parse_args()

    if args.file:
        with open(args.file) as f:
            content = f.read().strip()
    else:
        content = sys.stdin.read().strip()

    if not content:
        print("No content to log.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(LOG_DIR, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M")
    log_md = os.path.join(LOG_DIR, f"{today}.md")
    log_pdf = os.path.join(LOG_DIR, f"{today}.pdf")

    # Determine session number for today
    session_num = 1
    if os.path.exists(log_md):
        with open(log_md) as f:
            existing = f.read()
        session_num = existing.count("\n## Session ") + 1

    mode_tag = f" \u2014 {args.mode}" if args.mode else ""
    session_header = f"## Session {session_num} \u2014 {now_time}{mode_tag}"

    if session_num == 1:
        with open(log_md, "w") as f:
            f.write(f"# Portfolio Trader Log \u2014 {today}\n\n")
            f.write(f"{session_header}\n\n{content}\n")
    else:
        with open(log_md, "a") as f:
            f.write(f"\n\n---\n\n{session_header}\n\n{content}\n")

    print(f"Session {session_num} logged \u2192 {log_md}")

    # Regenerate PDF for the full day, then remove the .md
    try:
        result = subprocess.run(
            ["venv/bin/python3", PDF_SCRIPT, log_md, log_pdf],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            os.remove(log_md)
            print(f"PDF updated \u2192 {log_pdf}")
        else:
            print(f"PDF generation failed: {result.stderr.strip()}", file=sys.stderr)
            print(f"Markdown kept as fallback \u2192 {log_md}", file=sys.stderr)
    except Exception as e:
        print(f"PDF generation skipped: {e}", file=sys.stderr)
        print(f"Markdown kept as fallback \u2192 {log_md}")


if __name__ == "__main__":
    main()
