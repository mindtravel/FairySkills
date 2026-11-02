---
name: fairyppt
description: Build and maintain data-driven LaTeX (beamer) report decks whose every number is computed from project artefacts (CSV, manifests, eval outputs) by a generator script and rebuilt with one command. Use when the user asks for a progress / results / benchmark deck, to update an existing deck after new results, or to fix deck layout (overfull, wide headers, fonts).
---

# FairyPPT

One idea: **a deck is a build artefact.** A generator reads the project's data and writes the frame bodies; `fairyppt build`
turns them into a PDF. Nothing is typed into slides by hand, so the deck is rebuilt after every result instead of re-made.

## Workflow

```bash
fairyppt doctor                                     # xelatex, Noto Sans CJK SC, python deps
python3 gen_<deck>.py                               # data -> gen/<deck>_body.tex (frames)
fairyppt build <deck>.tex --out docs/ppt/<deck>.pdf --preview
```

`<deck>.tex` is a shell: `\input{fairyppt_style.tex}` (found through TEXINPUTS, set by `fairyppt build`), the title,
`\input{gen/<deck>_body.tex}`. The generator owns everything else.

## API

```python
from fairyppt import frame, tex, takeaway, title_frame   # frame(title, body, source="", kicker=None)
from fairyppt.longtable import frames                     # frames(title, header, rows, colspec, *, kicker, source, takeaway, groups, size)
from fairyppt import scores                               # scores.load(csv, spec.toml); scores.score_frames("tau2", "标题", tk=...)
from fairyppt.tables import export                        # export(rows, "x.csv", sheet) -> csv + xlsx
```

- `tex()` escapes a string for LaTeX; every value from data goes through it.
- `longtable.frames` paginates: fixed readable font, header repeated, "(i/n)" in the title, takeaway on the last page.
  Never shrink a font to fit a table on one page.
- `scores` is a table spec, not code: columns, probes (which `eval_name` belongs to which column), reference rows,
  and a dagger registry live in a TOML next to the deck. A new benchmark is a new `[bench.<name>]` block.

## Rules

- Numbers come from artefacts only (a CSV, a manifest, a scores.json); the generator cites the source in `\source{}`.
- One claim per frame, stated as a fact with its number; the takeaway box holds the one sentence to remember.
- Header cells must not be wider than their numbers: short labels, shared units in a `groups` row above.
- Kickers (`\sect{}`) name the section a frame belongs to; sources go in `\source{}`, not in the body.
- Characters the CJK sans font lacks (τ, ①②③, ≥ …) are written as math (`$\tau$`, `$\ge$`) before the body is saved.
- 8 pt text needs an explicit `\normalsize` reset inside tabulars; check `Overfull` in the build output and fix the
  frame, never the margin.
- Finished PDFs are copied to the project's `docs/ppt/`; build dirs are not committed.
- Mark rows a benchmark's own rules exclude (test-set training, same-domain data) with a dagger from the spec's
  registry; say so in the note. Never mix such rows with comparable ones in a ranking.

## Project-specific setup

Which CSV, which spec, which decks exist and where the PDFs go belong to the project (look for `slides/` and
`docs/ppt/` there), not to this skill.
