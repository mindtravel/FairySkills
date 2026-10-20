import json
from pathlib import Path

import pytest

from fairyview.build import build


def _jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _bench(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    _jsonl(data / "B_simple.json", [{"id": f"s{i}", "question": f"q{i}"} for i in range(3)])
    _jsonl(data / "B_irrelevance.json", [{"id": f"i{i}", "question": f"iq{i}"} for i in range(2)])
    (data / "B_index.json").write_text('{"simple": ["s0"]}', encoding="utf-8")
    _jsonl(data / "answers" / "B_simple.json", [{"id": f"s{i}", "ground_truth": [i]} for i in range(3)])
    return data


def _config(tmp_path: Path, extra: str = "") -> Path:
    cfg = tmp_path / "c.toml"
    cfg.write_text(
        f'''title = "b"
facets = ["_file"]
[sample]
n = 100
stratify = "_file"
[source]
kind = "columns_rows"
path = "data"
glob = "B_*.json"
exclude = ["B_index.json"]
id_field = "id"
panels = [{{ field = "question", label = "q" }}, {{ field = "ground_truth", label = "gold" }}]
[source.join]
path = "data/answers"
glob = "*.json"
on = "id"
{extra}''',
        encoding="utf-8",
    )
    return cfg


def _records(out: Path):
    text = (out / "records.js").read_text(encoding="utf-8")
    return json.loads(text[text.index("[") : text.rindex("]") + 1])


def test_join_file_facet_and_exclude(tmp_path: Path):
    _bench(tmp_path)
    out = build(str(_config(tmp_path)), str(tmp_path / "out"))
    manifest = json.loads((out / "manifest.json").read_text())
    records = _records(out)

    assert manifest["record_count"] == 5 and manifest["dropped"] == {}
    assert sorted(f["path"] for f in manifest["source_files"]) == ["B_irrelevance.json", "B_simple.json"]
    assert manifest["join"]["unmatched"] == 2
    assert {r["facets"]["_file"] for r in records} == {"B_simple.json", "B_irrelevance.json"}

    by_id = {r["id"]: r for r in records}
    assert [p["label"] for p in by_id["s1"]["panels"]] == ["q", "gold"]
    assert "1" in by_id["s1"]["panels"][1]["text"]
    assert [p["label"] for p in by_id["i0"]["panels"]] == ["q"]


def test_join_rejects_duplicate_keys(tmp_path: Path):
    data = _bench(tmp_path)
    _jsonl(data / "answers" / "dup.json", [{"id": "s0", "ground_truth": [9]}])
    with pytest.raises(ValueError, match="duplicate `id`"):
        build(str(_config(tmp_path)), str(tmp_path / "out"))


def test_join_unknown_column_fails(tmp_path: Path):
    _bench(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        build(str(_config(tmp_path, 'columns = ["nope"]')), str(tmp_path / "out"))


def _cat_config(tmp_path: Path, extra: str) -> Path:
    cfg = tmp_path / "c.toml"
    cfg.write_text(
        f'''title = "b"
[sample]
n = 100
[source]
kind = "columns_rows"
path = "data"
glob = "B_*.json"
exclude = ["B_index.json"]
{extra}
''',
        encoding="utf-8",
    )
    return cfg


def test_category_from_file_name_with_groups(tmp_path: Path):
    _bench(tmp_path)
    out = build(
        str(_cat_config(tmp_path, '''
[category]
from = "_file"
pattern = "B_(.*)\\\\.json"
groups = { "simple" = "with-answer", "irrelevance" = "no-answer" }
''')),
        str(tmp_path / "out"),
    )
    manifest = json.loads((out / "manifest.json").read_text())
    records = _records(out)
    cats = manifest["categories"]
    assert cats["name"] == "category"
    assert cats["rows"] == {"simple": 3, "irrelevance": 2}
    assert cats["shown"] == cats["rows"]
    assert cats["groups"] == {"no-answer": 2, "with-answer": 3}
    assert {r["facets"]["category"] for r in records} == {"simple", "irrelevance"}
    assert {r["facets"]["group"] for r in records} == {"with-answer", "no-answer"}


def test_category_from_a_column(tmp_path: Path):
    _jsonl(tmp_path / "data" / "L1.json", [{"id": "a", "Level": 1}, {"id": "b", "Level": 2}])
    cfg = tmp_path / "l.toml"
    cfg.write_text(
        'title = "l"\n'
        '[source]\nkind = "columns_rows"\npath = "data"\nglob = "L*.json"\nfacets = []\n'
        '[category]\nfrom = "Level"\nname = "level"\n',
        encoding="utf-8",
    )
    out = build(str(cfg), str(tmp_path / "out"))
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["categories"]["rows"] == {"1": 1, "2": 1}


def test_unmapped_category_fails_the_build(tmp_path: Path):
    _bench(tmp_path)
    with pytest.raises(ValueError, match="has no group"):
        build(
            str(_cat_config(tmp_path, '''
[category]
from = "_file"
pattern = "B_(.*)\\\\.json"
groups = { "simple" = "with-answer" }
''')),
            str(tmp_path / "out"),
        )


def test_unmatched_pattern_fails_the_build(tmp_path: Path):
    _bench(tmp_path)
    with pytest.raises(ValueError, match="does not match"):
        build(
            str(_cat_config(tmp_path, '''
[category]
from = "_file"
pattern = "NOPE_(.*)"
''')),
            str(tmp_path / "out"),
        )


def test_category_totals_are_the_population_not_the_sample(tmp_path: Path):
    """[category] totals must reflect every row in the source, even when
    `[sample]` keeps only a handful. Counting after sampling would make
    `rows` == `shown` for every category, always -- the bug this pins."""
    data = tmp_path / "data"
    _jsonl(data / "B_simple.json", [{"id": f"s{i}", "question": f"q{i}"} for i in range(40)])
    _jsonl(data / "B_irrelevance.json", [{"id": f"i{i}", "question": f"iq{i}"} for i in range(5)])
    cfg = tmp_path / "c.toml"
    cfg.write_text(
        f'''title = "b"
[sample]
n = 10
stratify = "category"
[source]
kind = "columns_rows"
path = "{data}"
glob = "B_*.json"
id_field = "id"
[category]
from = "_file"
pattern = "B_(.*)[.]json"
''',
        encoding="utf-8",
    )
    out = build(str(cfg), str(tmp_path / "out"))
    manifest = json.loads((out / "manifest.json").read_text())
    cats = manifest["categories"]
    assert cats["rows"] == {"simple": 40, "irrelevance": 5}
    assert cats["shown"]["simple"] < 40
    assert sum(cats["shown"].values()) == 10
