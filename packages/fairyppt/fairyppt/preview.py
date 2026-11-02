"""Render every page of a deck PDF to PNG plus a two-column contact sheet, for layout review."""
from pathlib import Path


def render(pdf, out=None):
    import fitz
    from PIL import Image, ImageDraw
    pdf = Path(pdf).resolve(); out = Path(out) if out else pdf.parent / "preview"
    out.mkdir(exist_ok=True, parents=True)
    doc = fitz.open(pdf)
    for old in out.glob("[0-9][0-9].png"):
        old.unlink()
    sheet = Image.new("RGB", (1600, ((len(doc) + 1) // 2) * 465), "#dddddd")
    for i, page in enumerate(doc):
        path = out / f"{i + 1:02}.png"
        page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(path)
        im = Image.open(path); im.thumbnail((790, 445))
        sheet.paste(im, ((i % 2) * 800, (i // 2) * 465))
        ImageDraw.Draw(sheet).text(((i % 2) * 800 + 8, (i // 2) * 465 + 445), str(i + 1), fill="black")
    sheet.save(out / "all-pages.png")
    return len(doc), out
