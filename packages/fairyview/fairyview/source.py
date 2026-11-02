"""Source resolution: which files, which columns, and what is missing.

Adapters no longer locate files or decide projections. They ask a `Source` for
the rows they need and name the columns they intend to read; the Source checks
those names against the real schema and fails with the available columns.

That check exists because the previous per-adapter behaviour was inconsistent:
`chat_rows` silently produced an empty page when its default facet column was
absent, while `hf_rows` raised. One place, one answer.
"""

from __future__ import annotations

import fnmatch
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import NamedTuple

from fairyview.rows import (
    PARQUET_SUFFIXES,
    iter_files,
    iter_light_rows,
    iter_rows,
    parquet_columns,
    parquet_row_count,
    read_jsonl_at,
    read_rows_at,
    scan_jsonl,
    is_seekable_jsonl,
)


class Key(NamedTuple):
    """Row address. `offset` is the byte offset for plain JSONL, else None."""

    file: str
    index: int
    offset: int | None = None


# Virtual column: the row's file, relative to `path`. Benchmarks often encode
# the category only in the file name (BFCL_v4_simple_python.json).
FILE_COLUMN = "_file"


@dataclass
class Join:
    """`[source.join]`: columns looked up by key in other raw files (left join).

    Rows without a match keep their own columns; the count is reported, not
    dropped, because a missing answer can be part of the data (BFCL
    irrelevance has no ground truth by design).
    """

    on: str
    columns: tuple[str, ...]
    rows: dict
    files: tuple[str, ...]
    root: str = ""
    unmatched: int = 0

    def relative(self, file_path: str) -> str:
        return os.path.relpath(file_path, self.root) if os.path.isdir(self.root) else os.path.basename(file_path)


@dataclass(frozen=True)
class Source:
    path: str
    glob: str
    files: tuple[str, ...]
    columns: tuple[str, ...]
    root: str
    # (size, mtime_ns) per file at load time. Row keys carry byte offsets, so a
    # file rewritten between scan and read would return the wrong rows.
    stamps: tuple[tuple[int, int], ...] = ()
    file_columns: tuple[str, ...] = ()
    join: Join | None = None

    @property
    def is_parquet(self) -> bool:
        return bool(self.files) and self.files[0].endswith(PARQUET_SUFFIXES)

    def relative(self, file_path: str) -> str:
        return os.path.relpath(file_path, self.root) if os.path.isdir(self.root) else os.path.basename(file_path)

    def has(self, column: str) -> bool:
        return column in self.columns

    def missing(self, wanted) -> list[str]:
        return [c for c in wanted if c and c not in self.columns]

    def require(self, wanted, *, owner: str) -> None:
        missing = self.missing(wanted)
        if missing:
            raise ValueError(
                f"{owner}: columns {missing} not found in {self.path!r}; available: {list(self.columns)}"
            )

    def resolve(self, column: str | None, role: str, *, owner: str) -> str:
        """Configured column, else the role's first match; else fail."""
        from fairyview import roles

        if column:
            self.require([column], owner=owner)
            return column
        found = roles.find(self.columns, role)
        if not found:
            raise ValueError(
                f"{owner}: no {role} column found; available: {list(self.columns)}. "
                f"Set the matching field in [source] explicitly."
            )
        return found

    def iter_index(self, projection, *, owner: str) -> Iterator[tuple[Key, dict]]:
        """Stream (file, index) keys with only the projected columns decoded.

        A generator, not a list: sampling consumes the stream and keeps `n`
        items, so a 1M-row file costs one rolling window rather than a
        1M-entry list.
        """
        projection = [c for c in projection if c]
        if projection:
            self.require(projection, owner=owner)
        file_projection = self._file_projection(projection)
        for file_path in self.files:
            if is_seekable_jsonl(file_path):
                rows = ((Key(file_path, i, offset), row)
                        for i, (offset, row) in enumerate(scan_jsonl(file_path, file_projection)))
            elif file_projection:
                rows = ((Key(file_path, i), row)
                        for i, row in enumerate(iter_light_rows(file_path, file_projection)))
            elif file_path.endswith(PARQUET_SUFFIXES):
                rows = ((Key(file_path, i), {}) for i in range(parquet_row_count(file_path)))
            else:
                rows = ((Key(file_path, i), {}) for i, _ in enumerate(iter_rows(file_path)))
            for key, row in rows:
                yield key, self._enrich(row, file_path, count=False)

    def _file_projection(self, projection) -> list[str]:
        """Columns to read from the files themselves: no virtual or joined ones,
        plus the join key when a joined column is needed."""
        wanted = [c for c in projection if c in self.file_columns]
        if self.join and any(c in self.join.columns for c in projection) and self.join.on not in wanted:
            wanted.append(self.join.on)
        return wanted

    def _enrich(self, row, file_path: str, *, count: bool) -> dict:
        row = dict(row.as_dict() if hasattr(row, "as_dict") else row)
        row[FILE_COLUMN] = self.relative(file_path)
        if self.join:
            match = self.join.rows.get(_join_key(row.get(self.join.on)))
            if match is None:
                if count:
                    self.join.unmatched += 1
            else:
                for column in self.join.columns:
                    row.setdefault(column, match.get(column))
        return row

    def check_unchanged(self) -> None:
        for file_path, stamp in zip(self.files, self.stamps):
            if _stamp(file_path) != stamp:
                raise RuntimeError(f"{file_path} changed while it was being read; rerun the build")

    def read(self, keys, projection) -> dict[Key, dict]:
        self.check_unchanged()
        by_file: dict[str, list[Key]] = {}
        for key in keys:
            by_file.setdefault(key.file, []).append(key)
        columns = self._file_projection([c for c in projection if c])
        decoded: dict[Key, dict] = {}
        for file_path, file_keys in by_file.items():
            if all(key.offset is not None for key in file_keys):
                rows = read_jsonl_at(file_path, [key.offset for key in file_keys])
                for key in file_keys:
                    decoded[key] = self._enrich(rows[key.offset], file_path, count=True)
                continue
            rows = read_rows_at(file_path, {key.index for key in file_keys}, columns)
            for key in file_keys:
                if key.index in rows:
                    decoded[key] = self._enrich(rows[key.index], file_path, count=True)
        return decoded


GLOB_FALLBACKS = ("**/*.parquet", "**/*.jsonl", "**/*.json")
COMPRESSED_SUFFIXES = (".gz", ".bz2", ".xz", ".zst")


def _files_for(path: str, pattern: str | None) -> tuple[list[str], str]:
    """Configured glob, else the first fallback that matches something.

    Datasets arrive as parquet, JSONL, or a single JSON array. Defaulting to
    parquet alone silently excluded the other two. Compressed files are
    rejected in `load_source`: byte offsets need a seekable plain file.
    """
    if pattern:
        return iter_files(path, pattern), pattern
    if os.path.isfile(path):
        return [path], os.path.basename(path)
    errors: list[str] = []
    for candidate in GLOB_FALLBACKS:
        try:
            return iter_files(path, candidate), candidate
        except FileNotFoundError as exc:
            errors.append(str(exc))
    raise FileNotFoundError(f"no data files under {path!r}; tried {list(GLOB_FALLBACKS)}")


def _join_key(value):
    # Keys may be ints in one file and strings in another; lists are unhashable.
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def _excluded(files: list[str], root: str, patterns) -> list[str]:
    if not patterns:
        return files
    if isinstance(patterns, str):
        patterns = [patterns]
    keep = []
    for file_path in files:
        rel = os.path.relpath(file_path, root) if os.path.isdir(root) else os.path.basename(file_path)
        if not any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(os.path.basename(file_path), p) for p in patterns):
            keep.append(file_path)
    if not keep:
        raise FileNotFoundError(f"`exclude` {list(patterns)} removed every file under {root!r}")
    return keep


def load_join(cfg: dict) -> Join:
    for key in ("path", "on"):
        if not cfg.get(key):
            raise ValueError(f"[source.join] needs `{key}`")
    path = os.path.expanduser(cfg["path"])
    files, _ = _files_for(path, cfg.get("glob"))
    files = _excluded(files, path, cfg.get("exclude"))
    on = cfg["on"]
    rows: dict = {}
    seen: list[str] = []
    for file_path in files:
        for index, row in enumerate(iter_rows(file_path)):
            if not isinstance(row, dict):
                continue
            if on not in row:
                raise ValueError(f"[source.join] row {index} of {file_path} has no `{on}`")
            key = _join_key(row[on])
            if key in rows:
                raise ValueError(f"[source.join] duplicate `{on}` = {row[on]!r} in {file_path}")
            rows[key] = row
            seen.extend(c for c in row if c not in seen)
    columns = tuple(cfg.get("columns") or [c for c in seen if c != on])
    missing = [c for c in columns if c not in seen]
    if missing:
        raise ValueError(f"[source.join] columns {missing} not found; available: {seen}")
    return Join(on=on, columns=columns, rows=rows, files=tuple(files), root=path)


def load_source(cfg: dict) -> Source:
    path = os.path.expanduser(cfg["path"])
    files, pattern = _files_for(path, cfg.get("glob"))
    files = _excluded(files, path, cfg.get("exclude"))
    compressed = [f for f in files if f.endswith(COMPRESSED_SUFFIXES)]
    if compressed:
        raise ValueError(
            f"compressed files are not read directly: {compressed[:5]}. "
            f"Decompress first (e.g. `gunzip -k <file>`) and point `glob` at the result."
        )
    columns: list[str] = []
    # Union of every file's schema, not just the first file's. Benchmark
    # directories hold per-split files whose columns differ (BFCL: only some
    # splits carry `ground_truth`).
    for file_path in files:
        for name in _file_columns(file_path):
            if name not in columns:
                columns.append(name)
    if not columns:
        raise ValueError(f"no columns found under {path!r} / {pattern!r}")
    join = load_join(cfg["join"]) if cfg.get("join") else None
    if join and join.on not in columns:
        raise ValueError(f"[source.join] key `{join.on}` is not a column of the source; available: {columns}")
    extra = [FILE_COLUMN] + [c for c in (join.columns if join else ()) if c not in columns]
    return Source(
        path=path,
        glob=pattern,
        files=tuple(files),
        columns=tuple(columns + extra),
        root=path,
        stamps=tuple(_stamp(f) for f in files),
        file_columns=tuple(columns),
        join=join,
    )


def _stamp(file_path: str) -> tuple[int, int]:
    stat = os.stat(file_path)
    return stat.st_size, stat.st_mtime_ns


def _file_columns(file_path: str) -> list[str]:
    """Column names of one file: parquet footer, else the first row's keys."""
    footer = parquet_columns(file_path)
    if footer:
        return footer
    from fairyview.rows import iter_rows

    for row in iter_rows(file_path):
        if isinstance(row, dict):
            return list(row)
    return []
