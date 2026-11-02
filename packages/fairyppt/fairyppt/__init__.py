"""FairyPPT: data-driven beamer decks that are rebuilt, not re-made.

  from fairyppt import frame, tex, takeaway, title_frame      one frame / escaping / the takeaway box / the title page
  from fairyppt.longtable import frames                        a table over as many frames as it needs
  from fairyppt import scores                                  score tables from an experiments CSV + TOML spec
  from fairyppt.tables import export                           csv + xlsx export of a table
  fairyppt build deck.tex --out out.pdf                        xelatex x2 with the style on TEXINPUTS, Overfull report, preview
"""
from .deck import frame, takeaway, tex, title_frame  # noqa: F401

STYLE_DIR = __import__("pathlib").Path(__file__).resolve().parent / "style"
STYLE_FILE = "fairyppt_style.tex"
