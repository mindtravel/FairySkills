"""Dataset-batch tables: CSV is the canonical, git-diffable form; the .xlsx (for pasting into Tencent Docs as a
real table) is always rebuilt from that CSV, never from in-memory rows."""
import csv

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER = ["数据批次", "规模与内容", "质量判断", "主要问题", "建议用途"]
WIDTHS = [26, 32, 32, 40, 26]


def write_csv(path, rows, header=HEADER):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print("wrote", path, f"({len(rows)} rows)")


def write_xlsx_from_csv(csv_path, xlsx_path, title, widths=None):
    with open(csv_path, encoding="utf-8-sig") as f:
        table = list(csv.reader(f))
    header, rows = table[0], table[1:]
    widths = widths or WIDTHS
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(header)
    for c in range(1, len(header) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="315FB4")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for r in rows:
        ws.append(r)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    wb.save(xlsx_path)
    print("wrote", xlsx_path, f"({len(rows)} rows)")


def export(rows, csv_path, title, header=HEADER, widths=None):
    write_csv(csv_path, rows, header)
    write_xlsx_from_csv(csv_path, csv_path[:-len(".csv")] + ".xlsx", title, widths)
