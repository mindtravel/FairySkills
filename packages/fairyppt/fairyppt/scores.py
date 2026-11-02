"""Score tables from an experiments CSV, driven by a TOML spec: one row per thing a reader compares (reference lines,
then one row per dataset family / training config with replicates averaged, then named mixes), paginated by longtable.

  load(csv, spec)              read the CSV path and the spec (see below); call once before anything else
  score_frames(bench, title)   LaTeX frames (one table over as many pages as needed)
  groups / agg / name / off_limits / by_run / ds_label / config_suffix   building blocks the deck generators use

Spec (TOML):
  [refs]        route -> label of a reference row (e.g. teacher / instruct / base)
  [refs_short]  route -> short label used when a reference row has no datasets (optional; defaults to [refs])
  [labels]      all_rows / mix_more / section_single / section_mix / source_suffix (optional; Chinese defaults)
  [dagger]      toml, list_key, name_key, benches_key, members_key: the registry that says which dataset families a
                benchmark's rules exclude; such rows get a dagger on that benchmark's tables (optional)
  [bench.<name>] kind (CSV `kind` filter; omit for any), kinds (list filter), main = [probe, col], note,
                probe = [[regex, probe], ...] (first match on eval_name wins; "" matches all),
                columns = [{label, col, probe, group?}, ...]
CSV columns used: kind, route, source, datasets, run, eval, eval_name, budget_m, max_len, epochs, sources_txt + score columns."""
import collections, csv, re, statistics, tomllib
from pathlib import Path

from .longtable import frames
from .deck import tex

CSV, BENCH, REF_LABEL, REF_SHORT, OFF, LABELS = None, {}, {}, {}, {}, {}
_DEFAULT_LABELS = {"all_rows": " 全量", "mix_more": "{a}+{b} 等 {n} 个家族", "section_single": "单个数据集 SFT（每个版本 × 训练量 × epoch 一行，按主分排序）",
                   "section_mix": "混合与 RFT", "source_suffix": " ×n = n 次重复的均值。数据版本与处理步骤见 experiments.csv 的 recipe 列。"}
num = lambda x: float(x) if x not in ("", None) else None
cell = lambda x: "--" if x is None else f"{x:.1f}"


def _probe_fn(rules):
    rules = [(re.compile(p), name) for p, name in rules]
    return lambda e: next((name for pat, name in rules if pat.search(e or "")), None)


def load(csv_path, spec_path):
    """Point the module at a CSV and a spec. Relative paths inside the spec are relative to the spec file."""
    global CSV, BENCH, REF_LABEL, REF_SHORT, OFF, LABELS, _BY_RUN
    spec_path = Path(spec_path); sp = tomllib.loads(spec_path.read_text())
    CSV = Path(csv_path); _BY_RUN = {}
    REF_LABEL = dict(sp.get("refs", {})); REF_SHORT = {**REF_LABEL, **sp.get("refs_short", {})}
    LABELS = {**_DEFAULT_LABELS, **sp.get("labels", {})}
    BENCH = {}
    for name, b in sp.get("bench", {}).items():
        BENCH[name] = {"kind": b.get("kind"), "kinds": b.get("kinds"), "main": tuple(b["main"]), "note": b.get("note", ""),
                       "probe": _probe_fn(b.get("probe", [["", "all"]])),
                       "columns": [(c["label"], c["col"], c["probe"], *( [c["group"]] if c.get("group") else [])) for c in b["columns"]]}
    OFF = {}
    if "dagger" in sp:
        d = sp["dagger"]; reg = tomllib.loads((spec_path.parent / d["toml"]).read_text())
        for f in reg.get(d.get("list_key", "family"), []):
            for bench in f.get(d.get("benches_key", "off_limits"), []):
                OFF.setdefault(bench, []).extend([f[d.get("name_key", "name")], *(f.get(d.get("members_key", "members")) or {})])
    return BENCH





def ds_label(r):
    """How a row's training data is named on every slide: what experiments.csv `datasets` records (family@vN).
    One dataset -> "family@vN"; a mix -> its families joined by "+" (first two + count when more than three)."""
    ds = [d for d in r.get("datasets", "").split(",") if d]
    if not ds:
        return REF_SHORT.get(r.get("route"), "")
    if len(ds) == 1:
        return ds[0]
    fams = [d.split("@")[0] for d in ds]
    return "+".join(fams) if len(fams) <= 3 else LABELS["mix_more"].format(a=fams[0], b=fams[1], n=len(fams))


def off_limits(r, bench):
    """Trained on data the benchmark's rules exclude ([dagger] registry); the row is marked dagger on that benchmark's tables."""
    return any(n in (r.get(c) or "") for n in OFF.get(bench, []) for c in ("datasets", "sources_txt", "run", "source"))


def name(r, bench=None):
    """ds_label + training config (budget, length, epochs): the full row label, LaTeX-escaped; † = off limits on bench."""
    return tex(ds_label(r)) + config_suffix(r) + ("$^\\dagger$" if bench and off_limits(r, bench) else "")


def by_run(run):
    """The experiments.csv row of a run (any of its evals), for pages keyed by run."""
    if not _BY_RUN:
        for r in rows():
            for k in (r["run"], r["eval"], r["eval"].split(":")[0]):
                _BY_RUN.setdefault(k, r)
    return _BY_RUN.get(run)


_BY_RUN = {}


def rows():
    return list(csv.DictReader(open(CSV)))


def group_key(r):
    if r["route"] in REF_LABEL:
        return ("ref", r["route"])
    if r["route"] not in ("rft", "mix") and "," not in r["source"]:
        # one row per training config: version, budget (empty = all rows), epochs, length; replicates (data seeds) share it
        return ("sub", r["datasets"], r["budget_m"], r["epochs"], r["max_len"])
    return ("run", re.sub(r"_(dseed|seed)\d+$", "", r["run"]))


def groups(bench):
    b = BENCH[bench]
    sel = [r for r in rows() if (b["kind"] is None or r["kind"] == b["kind"]) and any(num(r[c[1]]) is not None for c in b["columns"])]
    if b.get("kinds"):
        sel = [r for r in sel if r["kind"] in b["kinds"]]
    g = collections.defaultdict(list)
    for r in sel:
        if r["route"] not in REF_LABEL and not r["source"]:
            continue
        g[group_key(r)].append(r)
    return g


def agg(bench, rs):
    b = BENCH[bench]
    out, n = {}, {}
    for label, col, probe, *_ in b["columns"]:
        vals = [num(r[col]) for r in rs if b["probe"](r["eval_name"]) == probe and num(r[col]) is not None]
        out[(col, probe)] = statistics.mean(vals) if vals else None
        n[probe] = max(n.get(probe, 0), len(vals))
    return out, n


def config_suffix(r):
    b = num(r["budget_m"]); s = f" {b:g}M" if b else (LABELS["all_rows"] if r.get("route") not in REF_LABEL else "")
    if r["max_len"] not in ("", "10923"):
        s += f"/{int(r['max_len']) // 1024}k"
    if r["epochs"] not in ("", "1"):
        s += f"/ep{r['epochs']}"
    return s


def table_rows(bench):
    """longtable rows: ("section", label) | ("row", cells)."""
    b = BENCH[bench]
    g = groups(bench)
    main_probe, main_col = b["main"]
    score = lambda k: agg(bench, g[k])[0].get((main_col, main_probe)) or 0

    def cells(label, k):
        vals, n = agg(bench, g[k])
        out = [label]
        for _, col, probe, *_ in b["columns"]:
            v = cell(vals.get((col, probe)))
            if (col, probe) == (main_col, main_probe):
                v = f"\\textbf{{{v}}}" + (f"×{n[probe]}" if n.get(probe, 1) > 1 else "")
            out.append(v)
        return ("row", out)
    out = []
    for route in ("teacher", "instruct", "base"):
        if ("ref", route) in g:
            out.append(cells(REF_LABEL[route], ("ref", route)))
    subs = sorted((k for k in g if k[0] == "sub"), key=lambda k: -score(k))
    if subs:
        out.append(("section", LABELS["section_single"]))
        out += [cells(name(g[k][0], bench), k) for k in subs]
    runs = sorted((k for k in g if k[0] == "run"), key=lambda k: -score(k))
    if runs:
        out.append(("section", LABELS["section_mix"]))
        for k in runs:
            out.append(cells(name(g[k][0], bench), k))
    return out


def score_frames(bench, title, kicker="结果", tk=""):
    b = BENCH[bench]
    header = ["模型 / 数据"] + [c[0] for c in b["columns"]]
    groups, i = [], 0  # consecutive columns with the same 4th field share one header cell above their short labels
    while i < len(b["columns"]):
        g = b["columns"][i][3] if len(b["columns"][i]) > 3 else None
        j = i
        while j + 1 < len(b["columns"]) and g and len(b["columns"][j + 1]) > 3 and b["columns"][j + 1][3] == g:
            j += 1
        if g:
            groups.append((i + 1, j - i + 1, g))
        i = j + 1
    return frames(title, header, table_rows(bench), "l" + "r" * len(b["columns"]), kicker=kicker, groups=groups or None,
                  source=b["note"] + LABELS["source_suffix"], takeaway=tk)
