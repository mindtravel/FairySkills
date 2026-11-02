"""Long tables for the LaTeX decks: one table, as many frames as its rows need, at a font people can read.

Every generated deck used to squeeze a table into one frame by shrinking the font (down to 5 pt). This module
paginates instead: fixed row height, a fixed number of body rows per frame, the header repeated on every page,
section labels carried over when a section continues, "(i/n)" in the title, the takeaway on the last page.

  from longtable import frames
  frames(title, header, rows, colspec, *, kicker=None, source="", takeaway="", size="normal",
         per_page=None, rowsep="\\\\")  -> list[str] of LaTeX frames

  header   list of column labels (already LaTeX-escaped)
  rows     list of Row: ("section", label) | ("row", [cells...]) | ("rule",)
  colspec  tabularx column spec, e.g. "lrrrr" or "p{30mm} Y r r"  (Y = expanding column from tabularx)
  groups   [(first_col, span, label), ...] (0-based): a header row above the column labels, so columns that share a
           unit or scope ("%", "全量 278 题") carry it once and keep short labels of their own
  size     "normal" (6.4 pt, 19 lines) | "dense" (5.8 pt, 23 lines) | "loose" (7.2 pt, 16 lines); per_page overrides;
           a line budget, not a row count: a row costs as many lines as its tallest wrapped cell
The frame shell (\\begin{frame}[t]{title}, \\source, \\sect) is the same one deck_lib.frame emits, so decks mix freely.
"""
import re

SIZES = {"normal": ("\\fontsize{6.4}{8.2}\\selectfont", 19), "dense": ("\\fontsize{5.8}{7.4}\\selectfont", 23), "loose": ("\\fontsize{7.2}{9.4}\\selectfont", 16)}  # lines that fit above the footer with a title


def _frame(title, body, source, kicker):
    k = f"\\sect{{{kicker}}}\n" if kicker else ""
    return f"%{'-' * 60}\n{k}\\begin{{frame}}[t]{{{title}}}\\relax\n{body}\n\\source{{{source}}}\n\\end{{frame}}\n"


def _lines(cells, widths_chars):
    """Lines a row takes: the tallest cell, wrapping at its column's width (chars at this font)."""
    n = 1
    for c, w in zip(cells, widths_chars):
        txt = re.sub(r"\\[a-zA-Z]+\{|[{}]|\\\\", "", str(c))
        if w:
            width = sum(2 if ord(ch) > 0x2E80 else 1 for ch in txt)  # a CJK character is two Latin widths
            n = max(n, -(-width // w))
    return n


def _col_chars(colspec, ncol, size):
    """Approximate characters per line per column: fixed p{..mm} widths, Y = what is left, l/r/c = unlimited (no wrap)."""
    per_mm = {"normal": 0.88, "dense": 0.97, "loose": 0.78}[size]  # Latin-width units per mm at that font (a CJK char = 2 units)
    specs = re.findall(r"p\{([\d.]+)mm\}|([lrcY])", colspec)
    fixed = sum(float(mm) for mm, _ in specs if mm)
    n_y = sum(1 for mm, t in specs if t == "Y")
    text_mm = 148  # \textwidth: 160 mm 16:9 paper minus two 6 mm margins (shared/slides_style.tex)
    sep_mm = 2.1 * len(specs)  # \tabcolsep 3pt on both sides of every column
    y_mm = max(20, (text_mm - fixed - sep_mm - 12 * sum(1 for mm, t in specs if t and t in "lrc")) / n_y) if n_y else 0
    out = []
    for mm, t in specs:
        out.append(int(float(mm) * per_mm) if mm else (int(y_mm * per_mm) if t == "Y" else 0))
    return (out + [0] * ncol)[:ncol]


def frames(title, header, rows, colspec, *, kicker=None, source="", takeaway="", size="normal", per_page=None, tabcolsep="3pt", groups=None):
    font, n_per = SIZES[size]
    n_per = (per_page or n_per) - (1 if groups else 0)
    widths = _col_chars(colspec, len(header), size)
    ncol = len(header)
    wide = "Y" in colspec or "p{" in colspec
    env = "tabularx" if wide else "tabular"
    width = "{\\textwidth}" if wide else ""
    head = " & ".join(f"\\point{{{h}}}" for h in header) + "\\\\\\midrule\n"
    if groups:
        starts = {g[0]: g for g in groups}
        cells, c = [], 0
        while c < ncol:
            if c in starts:
                _, span, lab = starts[c]; cells.append(f"\\multicolumn{{{span}}}{{c}}{{\\point{{{lab}}}}}"); c += span
            else:
                cells.append(""); c += 1
        rules = "".join(f"\\cmidrule(lr){{{g[0] + 1}-{g[0] + g[1]}}}" for g in groups)
        head = " & ".join(cells) + "\\\\" + rules + "\n\\rowcolor{pale}" + head
    # split into pages: a section label never ends a page; a continued section repeats its label with （续）
    pages, cur, used, cur_section = [], [], 0, None
    for r in rows:
        cost = 1 if r[0] != "row" else _lines(r[1], widths)
        if r[0] == "section":
            cur_section = r[1]
            if used >= n_per - 2:  # a section label never ends a page
                pages.append(cur); cur, used = [], 0
            cur.append(r); used += 1
            continue
        if used + cost > n_per and cur:
            pages.append(cur); cur, used = [], 0
            if cur_section:
                cur.append(("section", cur_section + "（续）")); used += 1
        cur.append(r); used += cost
    if cur:
        pages.append(cur)
    out = []
    for i, body_rows in enumerate(pages):
        lines = []
        for r in body_rows:
            if r[0] == "section":
                lines.append(f"\\multicolumn{{{ncol}}}{{l}}{{\\textit{{{r[1]}}}}}\\\\")
            elif r[0] == "rule":
                lines.append("\\midrule")
            else:
                lines.append(" & ".join(str(c) for c in r[1]) + "\\\\")
        body = (f"\\vspace{{-1mm}}{{{font}\\renewcommand{{\\arraystretch}}{{1.04}}\\setlength{{\\tabcolsep}}{{{tabcolsep}}}"
                f"\\begin{{{env}}}{width}{{{colspec}}}\\toprule\\rowcolor{{pale}}" + head + "\n".join(lines) + f"\n\\bottomrule\\end{{{env}}}\\par}}")
        if takeaway and i == len(pages) - 1:
            body += f"\\takeaway{{{takeaway}}}"
        t = title if len(pages) == 1 else f"{title}（{i + 1}/{len(pages)}）"
        out.append(_frame(t, body, source, kicker if i == 0 else None))
    return out
