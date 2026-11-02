"""Benchmark categories: a derived facet from a file name or a column.

Benchmarks declare their taxonomy in different places: BFCL v4 in the file name
(`BFCL_v4_simple_python.json`), GAIA in a `Level` column, BrowseComp in `topic`.
One block covers all three, and the mapping stays in the config where a reviewer
can see it -- the tool does not carry any benchmark's taxonomy itself.

    [category]
    from = "_file"                      # `_file`, or any column
    pattern = "BFCL_v4_(.*)\\\\.json"     # one capture group; else the whole value
    name = "category"                   # facet name
    groups = { "live_simple" = "live" } # optional second-level facet
    default_group = "other"             # else an unmapped category is an error

An unmatched pattern or an unmapped category fails the build: a page whose
grouping is silently incomplete is worse than no grouping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

DEFAULT_NAME = "category"
DEFAULT_GROUP_NAME = "group"


@dataclass
class Category:
    source: str
    pattern: re.Pattern | None = None
    name: str = DEFAULT_NAME
    groups: dict[str, str] = field(default_factory=dict)
    group_name: str = DEFAULT_GROUP_NAME
    default_group: str | None = None
    totals: dict[str, int] = field(default_factory=dict)
    shown: dict[str, int] = field(default_factory=dict)

    def derive(self, value) -> dict[str, str]:
        """Row value -> {facet: value}. Raises when the taxonomy does not fit."""
        if value is None or value == "":
            raise ValueError(f"[category] `from = {self.source}` is empty for this row")
        text = str(value)
        if self.pattern is not None:
            match = self.pattern.search(text)
            if not match:
                raise ValueError(
                    f"[category] pattern {self.pattern.pattern!r} does not match {text!r}"
                )
            text = match.group(1) if match.groups() else match.group(0)
        out = {self.name: text}
        if self.groups:
            group = self.groups.get(text, self.default_group)
            if group is None:
                raise ValueError(
                    f"[category] {text!r} has no group; known categories: {sorted(self.groups)}. "
                    f'Add it to `groups`, or set `default_group`.'
                )
            out[self.group_name] = group
        return out

    def count(self, derived: dict[str, str] | None) -> None:
        if derived is None:
            return
        key = derived[self.name]
        self.totals[key] = self.totals.get(key, 0) + 1

    def count_shown(self, derived: dict[str, str] | None) -> None:
        if derived is None:
            return
        key = derived[self.name]
        self.shown[key] = self.shown.get(key, 0) + 1

    def group_totals(self) -> dict[str, int]:
        """Second-level counts, summed over categories."""
        if not self.groups:
            return {}
        out: dict[str, int] = {}
        for name, count in self.totals.items():
            group = self.groups.get(name, self.default_group) or "?"
            out[group] = out.get(group, 0) + count
        return dict(sorted(out.items()))


def parse(cfg: dict | None, columns=()) -> Category | None:
    if not cfg:
        return None
    source = cfg.get("from") or cfg.get("field")
    if not source:
        raise ValueError("[category] needs `from` (a column name or `_file`)")
    if columns and source not in columns:
        raise ValueError(f"[category] `from = {source!r}` is not a column; available: {list(columns)}")
    pattern = cfg.get("pattern")
    compiled = None
    if pattern:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"[category] pattern is not valid regex: {exc}") from exc
        if compiled.groups > 1:
            raise ValueError("[category] pattern must have at most one capture group")
    groups = dict(cfg.get("groups") or {})
    return Category(
        source=source,
        pattern=compiled,
        name=cfg.get("name", DEFAULT_NAME),
        groups=groups,
        group_name=cfg.get("group_name", DEFAULT_GROUP_NAME),
        default_group=cfg.get("default_group"),
    )
