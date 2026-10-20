"""Drive a view over a source: scan, sample, decode, render, assemble.

The only place that knows this order. Views supply columns and panels; the
driver supplies everything mechanical.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path

from fairyview import category as category_mod
from fairyview import mask
from fairyview.record import make_record
from fairyview.sample import sample_records
from fairyview.schema import ReviewRecord
from fairyview.source import Source
from fairyview.views import View, load_adapter, load_custom, registered

BATCH = 512


def _batches(items: Iterable, size: int = BATCH) -> Iterator[list]:
    batch: list = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _check_drops(view: View, dropped: list[tuple[str, int, str]], stats: dict) -> None:
    """Report every dropped row. Silence is what the user must never get.

    `[source] on_drop = "error"` turns any drop into a failure; the default is
    "report", which records counts per reason in the manifest and prints them
    to stderr so a build log shows the loss.
    """
    if not dropped:
        stats["dropped"] = {}
        return
    reasons = Counter(reason for _, _, reason in dropped)
    stats["dropped"] = dict(reasons)
    stats["dropped_examples"] = [
        {"file": source_rel, "row": index, "reason": reason}
        for source_rel, index, reason in dropped[:20]
    ]
    mode = str(view.cfg.get("on_drop", "report")).lower()
    summary = ", ".join(f"{reason}={count}" for reason, count in reasons.items())
    message = f"{view.name}: dropped {len(dropped)} rows ({summary})"
    if mode == "error":
        raise ValueError(message + "; set on_drop = \"report\" to accept partial data")
    print(f"warning: {message}", file=sys.stderr)


def records_from_view(
    view: View,
    mask_cfg: dict | None = None,
    stats: dict | None = None,
    category_cfg: dict | None = None,
) -> list[ReviewRecord]:
    """View -> records.

    The index is consumed as a stream. Sampling sees the whole stream but holds
    only `n` items; without sampling, keys are decoded in batches so a 1M-row
    file never turns into a 1M-entry Python list.
    """
    stats = stats if stats is not None else {}
    source = view.source
    facets = view.facets
    id_field = view.id_field

    wanted = [*facets, *([id_field] if id_field else [])]
    if wanted:
        source.require(wanted, owner=view.name)

    projection = list(dict.fromkeys([*view.columns(), *wanted]))
    stratify = (view.sample_cfg or {}).get("stratify")
    # A derived category is a facet too: make sure both its column and the
    # facet/stratify built from it are read.
    cat = category_mod.parse(category_cfg, source.columns if category_cfg else ())
    # `stratify` can name a real column, or the facet a `[category]` derives --
    # the latter is not a column of any file and must not be requested from one.
    stratify_is_derived = bool(cat) and stratify in (cat.name, cat.group_name)
    # The scan reads only cheap key columns; the full projection (often a
    # nested `messages` column) is decoded for sampled rows only. Scanning with
    # the full projection decoded every conversation of a 1M-row export.
    scan = list(dict.fromkeys([*wanted, *([stratify] if stratify and not stratify_is_derived else []),
                               *([cat.source] if cat else [])]))
    source.require(projection, owner=view.name)
    index = source.iter_index(scan, owner=view.name)

    # Counts population, not sample: `sample_records` touches every item of the
    # full stream exactly once (to stratify), which is the only point left
    # where the full population is visible. Counting after sampling returns
    # would silently measure the sample against itself ("rows" == "shown" for
    # every category, always) -- that bug shipped once; `on_item` is the fix.
    count_population = (lambda item: cat.count(cat.derive(item[1].get(cat.source)))) if cat else None
    if view.sample_cfg:
        index = sample_records(
            index,
            view.sample_cfg,
            facet_key=(
                (lambda item: cat.derive(item[1].get(cat.source)).get(stratify))
                if stratify_is_derived
                else (lambda item: item[1].get(stratify))
            )
            if stratify
            else (lambda item: None),
            on_item=count_population,
        )
        count_population = None  # already counted during sampling; do not count twice

    out: list[ReviewRecord] = []
    dropped: list[tuple[str, int, str]] = []
    stats["rows_examined"] = 0
    for batch in _batches(index):
        decoded = source.read([key for key, _ in batch], projection)
        for key, light in batch:
            stats["rows_examined"] += 1
            if count_population:
                count_population((key, light))
            row = decoded.get(key)
            if row is None:
                dropped.append((source.relative(key[0]), key[1], "row not decoded"))
                continue
            rendered = view.render(row)
            if rendered is None:
                dropped.append((source.relative(key[0]), key[1], "no panel produced"))
                continue
            rendered.panels = mask.finalize_panels(rendered.panels, mask_cfg)
            derived = cat.derive(row.get(cat.source)) if cat else None
            record = make_record(
                key=key,
                row=row,
                rendered=rendered,
                source=source,
                facets=facets,
                id_field=id_field,
                provenance=view.provenance(),
                extra_facets=derived,
            )
            if record is not None:
                out.append(record)
                if cat:
                    cat.count_shown(derived)

    if cat:
        stats["categories"] = _category_counts(cat)
    _check_drops(view, dropped, stats)
    stats["records"] = len(out)
    stats["source_files"] = [
        {"path": source.relative(path), "bytes": Path(path).stat().st_size,
         "mtime": Path(path).stat().st_mtime}
        for path in source.files
    ]
    if source.join:
        stats["join"] = {
            "on": source.join.on,
            "columns": list(source.join.columns),
            "files": [{"path": source.join.relative(p), "bytes": Path(p).stat().st_size}
                      for p in source.join.files],
            "unmatched": source.join.unmatched,
        }
    return out


def _resolve_paths(cfg: dict, base: Path) -> None:
    """Relative data paths are relative to the config file, not the cwd.

    The same config then builds from any directory, and a config shipped next
    to its data keeps working after both are moved together.
    """

    def resolve(value: str) -> str:
        path = Path(value).expanduser()
        return str(path if path.is_absolute() else (base / path).resolve())

    if isinstance(cfg.get("path"), str):
        cfg["path"] = resolve(cfg["path"])
    if isinstance(cfg.get("join"), dict) and isinstance(cfg["join"].get("path"), str):
        cfg["join"] = {**cfg["join"], "path": resolve(cfg["join"]["path"])}
    for side in ("left", "right"):
        if isinstance(cfg.get(side), dict) and isinstance(cfg[side].get("path"), str):
            cfg[side] = {**cfg[side], "path": resolve(cfg[side]["path"])}


def _category_counts(cat) -> dict:
    """Per-category totals: how many rows the source has, how many reached the page.

    Totals come from the scan, so a sampled page still shows the population.
    A readout of "22 of 22" is what tells a reviewer the sample covered the
    category; without it, a thin category looks like a small category.
    """
    return {"name": cat.name, "rows": cat.totals, "shown": cat.shown, "groups": cat.group_totals()}


def build_records(config: dict, config_path: Path, stats: dict | None = None) -> list[dict]:
    """Config -> serialized records.

    Every adapter validates its own config shape (`path` vs `left`/`right`)
    before any file is touched; the driver has no type switch.
    """
    # `facets` is usually written at the top level of the config, next to
    # [sample]; some configs put it inside [source]. Accept both: views and the
    # driver read it from one place.
    cfg = dict(config["source"])
    cfg["facets"] = config.get("facets") or cfg.get("facets") or []
    # `[mask]` is a top-level table; views read it from their config copy.
    cfg["mask"] = config.get("mask") or cfg.get("mask")
    cfg["category"] = config.get("category") or cfg.get("category")
    sample_cfg = config.get("sample") or cfg.get("sample")
    kind = cfg["kind"]
    _resolve_paths(cfg, config_path.parent)

    import fairyview.adapters  # noqa: F401  (registers built-ins)

    if ":" in kind or kind not in registered():
        adapter = load_custom(kind, base_dir=config_path.parent)
    else:
        adapter = load_adapter(kind)

    adapter.validate(cfg)
    stats = stats if stats is not None else {}
    records = adapter.records(cfg, sample_cfg, stats)
    if stats.get("records") is None:
        stats["records"] = len(records)
    return [record.to_dict() for record in records]
