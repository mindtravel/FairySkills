"""fairyppt build | preview | doctor | style"""
import argparse, os, re, shutil, subprocess, sys
from pathlib import Path

from . import STYLE_DIR, STYLE_FILE


def build(tex, out=None, passes=2, preview=False, build_dir=None):
    tex = Path(tex).resolve(); bd = Path(build_dir) if build_dir else tex.parent / "build"; bd.mkdir(exist_ok=True)
    env = {**os.environ, "TEXINPUTS": f"{STYLE_DIR}{os.pathsep}{os.environ.get('TEXINPUTS', '')}"}  # trailing sep keeps TeX's defaults
    log = bd / (tex.stem + ".log")
    for i in range(passes):
        r = subprocess.run(["xelatex", "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={bd}", tex.name], cwd=tex.parent, env=env, capture_output=True, text=True)
        if r.returncode:
            print(r.stdout[-3000:], file=sys.stderr); return 1
    over = [l for l in log.read_text(errors="ignore").splitlines() if l.startswith("Overfull")]
    pdf = bd / (tex.stem + ".pdf")
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(pdf, out); pdf = Path(out)
    print(f"wrote {pdf}" + (f"  ({len(over)} Overfull: " + "; ".join(o[:60] for o in over[:3]) + ")" if over else ""))
    if preview:
        from .preview import render
        n, d = render(pdf); print(f"preview: {n} pages -> {d}")
    return 0


def doctor():
    ok = True
    for tool in ("xelatex", "fc-list"):
        print(("ok  " if shutil.which(tool) else "MISSING ") + tool); ok &= bool(shutil.which(tool))
    fonts = subprocess.run(["fc-list", ":family"], capture_output=True, text=True).stdout if shutil.which("fc-list") else ""
    have = "Noto Sans CJK SC" in fonts
    print(("ok  " if have else "MISSING ") + "font Noto Sans CJK SC"); ok &= have
    for mod in ("fitz", "PIL", "openpyxl"):
        try:
            __import__(mod); print(f"ok   python {mod}")
        except ImportError:
            print(f"MISSING python {mod}"); ok = False
    print(("ok  " if (STYLE_DIR / STYLE_FILE).exists() else "MISSING ") + f"style {STYLE_DIR / STYLE_FILE}")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fairyppt"); sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="xelatex the deck with the FairyPPT style on TEXINPUTS")
    b.add_argument("tex"); b.add_argument("--out"); b.add_argument("--passes", type=int, default=2); b.add_argument("--preview", action="store_true"); b.add_argument("--build-dir")
    p = sub.add_parser("preview", help="PNG per page + contact sheet"); p.add_argument("pdf"); p.add_argument("out", nargs="?")
    sub.add_parser("doctor", help="check xelatex, fonts, python deps"); sub.add_parser("style", help="print the style directory (for TEXINPUTS)")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        return build(a.tex, a.out, a.passes, a.preview, a.build_dir)
    if a.cmd == "preview":
        from .preview import render
        n, d = render(a.pdf, a.out); print(f"Rendered {n} slides -> {d}"); return 0
    if a.cmd == "doctor":
        return doctor()
    print(STYLE_DIR); return 0


if __name__ == "__main__":
    sys.exit(main())
