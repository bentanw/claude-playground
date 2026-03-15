#!/usr/bin/env python3
"""
Convert a stock research markdown report to a clean PDF.
Usage: python3 pdf_report.py <input.md> <output.pdf>
"""

import argparse
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Palette ───────────────────────────────────────────────────────────────────
C_BLACK    = colors.HexColor("#1A1A1A")
C_DARK     = colors.HexColor("#2C2C2C")
C_MID      = colors.HexColor("#555555")
C_LIGHT    = colors.HexColor("#888888")
C_ACCENT   = colors.HexColor("#8B1A1A")   # deep red
C_GOLD     = colors.HexColor("#C9A84C")
C_BG_HEAD  = colors.HexColor("#F5F0E8")   # warm ivory for table headers
C_RULE     = colors.HexColor("#CCCCCC")
C_GREEN    = colors.HexColor("#1A6B1A")
C_RED      = colors.HexColor("#8B1A1A")
C_ORANGE   = colors.HexColor("#B8600A")
C_TABLE_ALT = colors.HexColor("#FAF7F2")  # alternating row tint

# ── Chinese font registration ─────────────────────────────────────────────────
_ZH_FONT_REGULAR = "STHeiti"
_ZH_FONT_BOLD    = "STHeiti-Bold"

def _register_zh_fonts():
    """Register STHeiti TTC fonts for Chinese rendering. Silently skips if unavailable."""
    candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/STHeiti Medium.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont(_ZH_FONT_REGULAR, path, subfontIndex=0))
                pdfmetrics.registerFont(TTFont(_ZH_FONT_BOLD,    path, subfontIndex=0))
                return True
            except Exception:
                continue
    return False


def _font(lang: str, bold: bool = False) -> str:
    if lang == "zh":
        return _ZH_FONT_BOLD if bold else _ZH_FONT_REGULAR
    return "Helvetica-Bold" if bold else "Helvetica"


def _font_oblique(lang: str) -> str:
    # STHeiti has no oblique variant — use regular for Chinese
    return _ZH_FONT_REGULAR if lang == "zh" else "Helvetica-Oblique"


# ── Styles ────────────────────────────────────────────────────────────────────
def build_styles(lang: str = "en"):
    base = getSampleStyleSheet()

    styles = {
        "title": ParagraphStyle(
            "title", fontName=_font(lang, bold=True), fontSize=20,
            textColor=C_BLACK, leading=26, spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", fontName=_font(lang), fontSize=10,
            textColor=C_MID, leading=14, spaceAfter=16,
        ),
        "h2": ParagraphStyle(
            "h2", fontName=_font(lang, bold=True), fontSize=13,
            textColor=C_ACCENT, leading=18, spaceBefore=18, spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "h3", fontName=_font(lang, bold=True), fontSize=11,
            textColor=C_DARK, leading=15, spaceBefore=10, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", fontName=_font(lang), fontSize=10,
            textColor=C_DARK, leading=15, spaceAfter=6,
        ),
        "body_bold": ParagraphStyle(
            "body_bold", fontName=_font(lang, bold=True), fontSize=10,
            textColor=C_BLACK, leading=15, spaceAfter=4,
        ),
        "bullet": ParagraphStyle(
            "bullet", fontName=_font(lang), fontSize=10,
            textColor=C_DARK, leading=14, leftIndent=16,
            bulletIndent=4, spaceAfter=3,
        ),
        "small": ParagraphStyle(
            "small", fontName=_font(lang), fontSize=8,
            textColor=C_LIGHT, leading=11, spaceAfter=4,
        ),
        "disclaimer": ParagraphStyle(
            "disclaimer", fontName=_font_oblique(lang), fontSize=8,
            textColor=C_MID, leading=12, leftIndent=10,
            borderPad=6, spaceAfter=6,
        ),
        "verdict_rating": ParagraphStyle(
            "verdict_rating", fontName=_font(lang, bold=True), fontSize=14,
            textColor=C_ACCENT, leading=20, spaceAfter=4,
        ),
    }
    return styles


def color_for_verdict(text: str):
    t = text.upper()
    if any(x in t for x in ["✅", "PASS", "EXCEPTIONAL", "STRONG", "HEALTHY", "LIQUID"]):
        return C_GREEN
    if any(x in t for x in ["❌", "FAIL", "NEGATIVE", "COLLAPSING", "BURN", "LOSING"]):
        return C_RED
    if any(x in t for x in ["⚠️", "ELEVATED", "BELOW", "MODERATE"]):
        return C_ORANGE
    return C_DARK


# ── Markdown parser → ReportLab flowables ────────────────────────────────────
def parse_md(md_text: str, styles: dict, lang: str = "en") -> list:
    """Convert markdown text to a list of ReportLab flowables."""
    flowables = []
    lines = md_text.splitlines()
    i = 0

    def sanitize(text: str) -> str:
        """Convert markdown inline formatting to ReportLab XML."""
        # bold+italic ***x*** or ___x___
        text = re.sub(r'\*\*\*(.*?)\*\*\*', r'<b><i>\1</i></b>', text)
        # bold **x**
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        # italic *x*
        text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
        # code `x`
        text = re.sub(r'`([^`]+)`', r'<font name="Courier" size="9">\1</font>', text)
        # escape bare & < > not inside tags
        # (simplified — good enough for stock reports)
        text = text.replace('&', '&amp;').replace('<b>', '\x01b\x02').replace('</b>', '\x01/b\x02') \
                   .replace('<i>', '\x01i\x02').replace('</i>', '\x01/i\x02') \
                   .replace('<font', '\x01font').replace('</font>', '\x01/font\x02')
        # don't double-escape angle brackets inside tags
        text = re.sub(r'<(?!\x01)', '&lt;', text)
        text = text.replace('\x01', '<').replace('\x02', '>')
        return text

    def is_table_row(line):
        return line.strip().startswith('|') and line.strip().endswith('|')

    def collect_table(start_idx):
        rows = []
        j = start_idx
        while j < len(lines) and is_table_row(lines[j]):
            cells = [c.strip() for c in lines[j].strip().strip('|').split('|')]
            rows.append(cells)
            j += 1
        return rows, j

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip blank lines / horizontal rules
        if not stripped or stripped in ('---', '***', '___'):
            if stripped == '---':
                flowables.append(HRFlowable(width="100%", thickness=0.5,
                                            color=C_RULE, spaceAfter=6, spaceBefore=6))
            else:
                flowables.append(Spacer(1, 4))
            i += 1
            continue

        # Code blocks — skip (research reports shouldn't have them)
        if stripped.startswith('```'):
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                i += 1
            i += 1
            continue

        # H1 title
        if stripped.startswith('# ') and not stripped.startswith('## '):
            title_text = sanitize(stripped[2:])
            flowables.append(Paragraph(title_text, styles["title"]))
            i += 1
            continue

        # H2
        if stripped.startswith('## '):
            flowables.append(Paragraph(sanitize(stripped[3:]), styles["h2"]))
            i += 1
            continue

        # H3
        if stripped.startswith('### '):
            flowables.append(Paragraph(sanitize(stripped[4:]), styles["h3"]))
            i += 1
            continue

        # Blockquote disclaimer
        if stripped.startswith('> '):
            text = sanitize(stripped[2:])
            flowables.append(Paragraph(text, styles["disclaimer"]))
            i += 1
            # collect continued blockquote lines
            while i < len(lines) and lines[i].strip().startswith('> '):
                flowables.append(Paragraph(sanitize(lines[i].strip()[2:]), styles["disclaimer"]))
                i += 1
            continue

        # Italic metadata line (e.g. *Analysis Date: ..*)
        if stripped.startswith('*') and stripped.endswith('*') and not stripped.startswith('**'):
            flowables.append(Paragraph(sanitize(stripped.strip('*')), styles["subtitle"]))
            i += 1
            continue

        # Table
        if is_table_row(stripped):
            rows, i = collect_table(i)
            # filter out separator rows (---|---|---)
            rows = [r for r in rows if not all(re.match(r'^[-:]+$', c) for c in r if c)]
            if not rows:
                continue

            col_count = max(len(r) for r in rows)
            # Pad short rows
            rows = [r + [''] * (col_count - len(r)) for r in rows]

            # Build cell paragraphs
            table_data = []
            for ri, row in enumerate(rows):
                cell_row = []
                for ci, cell in enumerate(row):
                    is_header = (ri == 0)
                    cell_color = color_for_verdict(cell) if (ri > 0 and ci == col_count - 1) else C_DARK
                    style = ParagraphStyle(
                        f"tc_{ri}_{ci}",
                        fontName=_font(lang, bold=is_header),
                        fontSize=9,
                        textColor=colors.white if is_header else cell_color,
                        leading=13,
                    )
                    cell_row.append(Paragraph(sanitize(cell), style))
                table_data.append(cell_row)

            # Column widths: first col wider, last col auto
            available = 6.5 * inch
            if col_count == 4:
                col_widths = [1.5*inch, 1.2*inch, 1.5*inch, 2.3*inch]
            elif col_count == 3:
                col_widths = [2.0*inch, 1.5*inch, 3.0*inch]
            else:
                col_widths = [available / col_count] * col_count

            tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
            tbl_style = TableStyle([
                # Header row
                ("BACKGROUND",  (0, 0), (-1, 0), C_ACCENT),
                ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
                ("FONTNAME",    (0, 0), (-1, 0), _font(lang, bold=True)),
                ("FONTSIZE",    (0, 0), (-1, 0), 9),
                # Alternating rows
                *[("BACKGROUND", (0, r), (-1, r), C_TABLE_ALT)
                  for r in range(2, len(table_data), 2)],
                ("GRID",        (0, 0), (-1, -1), 0.3, C_RULE),
                ("TOPPADDING",  (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
            ])
            tbl.setStyle(tbl_style)
            flowables.append(Spacer(1, 6))
            flowables.append(tbl)
            flowables.append(Spacer(1, 8))
            continue

        # Bullet / list item
        if stripped.startswith('- ') or stripped.startswith('* '):
            text = sanitize(stripped[2:])
            flowables.append(Paragraph(f"• {text}", styles["bullet"]))
            i += 1
            continue

        # Numbered list
        m = re.match(r'^(\d+)\.\s+(.*)', stripped)
        if m:
            text = sanitize(m.group(2))
            flowables.append(Paragraph(f"{m.group(1)}. {text}", styles["bullet"]))
            i += 1
            continue

        # Verdict rating line (bold, larger)
        if stripped.startswith('**Overall Rating') or stripped.startswith('**Stance'):
            flowables.append(Paragraph(sanitize(stripped), styles["verdict_rating"]))
            i += 1
            continue

        # Regular paragraph
        flowables.append(Paragraph(sanitize(stripped), styles["body"]))
        i += 1

    return flowables


def make_page_number_fn(lang: str = "en"):
    footer_text = (
        "股票研究报告 — 仅供参考，不构成投资建议。"
        if lang == "zh"
        else "Stock Research Report — For informational purposes only. Not financial advice."
    )
    font_name = _font(lang)

    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont(font_name, 8)
        canvas.setFillColor(C_LIGHT)
        canvas.drawRightString(
            doc.pagesize[0] - inch,
            0.5 * inch,
            f"Page {doc.page}"
        )
        canvas.drawString(inch, 0.5 * inch, footer_text)
        canvas.restoreState()

    return add_page_number


def md_to_pdf(md_path: str, pdf_path: str, lang: str = "en"):
    if lang == "zh":
        _register_zh_fonts()
    if md_path == "-":
        md_text = sys.stdin.read()
    else:
        md_text = Path(md_path).read_text(encoding="utf-8")
    styles  = build_styles(lang)
    story   = parse_md(md_text, styles, lang)

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=LETTER,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=inch,
        bottomMargin=0.75 * inch,
        title=Path(md_path).stem,
    )
    pn_fn = make_page_number_fn(lang)
    doc.build(story, onFirstPage=pn_fn, onLaterPages=pn_fn)
    print(f"PDF saved → {pdf_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert stock research markdown to PDF.")
    parser.add_argument("input_md",  help="Path to input .md file")
    parser.add_argument("output_pdf", help="Path to output .pdf file")
    parser.add_argument("--lang", default="en", choices=["en", "zh"],
                        help="Report language: en (English) or zh (Mandarin Chinese)")
    args = parser.parse_args()
    md_to_pdf(args.input_md, args.output_pdf, lang=args.lang)
