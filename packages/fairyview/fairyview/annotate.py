"""AI annotation: an LLM marks suspicious spans in a record's panels and gives a verdict.

Runs as a wrapper around any adapter (`[annotate]` in the config), so the same code reviews SFT data,
cleaning output, benchmark items and eval trajectories. The model never reports offsets: it quotes the
suspicious text verbatim and this module finds it in the panel, so a span is either exact or dropped
(dropped quotes are counted in the manifest, never silently kept).

Blind by construction: only the panels named in `panels` are sent, with neutral labels (panel 1, panel 2 ...),
so facets such as the data source or the right/wrong label never reach the model.

    [annotate]
    model = "deepseek-v4.1-flash-1017"
    base_url = "https://maas.tatucloud.com/v1"
    key_file = "~/.codex/auth_tatu.json"     # JSON {"OPENAI_API_KEY": ...}; the key is never logged
    panels = ["prompt", "trajectory"]         # panel fields sent to the model, in this order
    task_panel = "prompt"                     # the panel that states the task (requirements are quoted from it)
    targets = ["trajectory", "base_trajectory"]  # optional: review each of these separately, each paired with the
                                              # task panel (e.g. a fine-tuned model vs base); the model never learns
                                              # which one it sees. Facets: ai_<name> for the first, ai_<name>_<role> after.
    instructions = "..."                      # what counts as suspicious, written for the task
    only = { diff_class = ["fixed", "broken"] }  # optional facet filter: other records pass through unannotated
    max_chars = 60000                         # per panel; longer text is cut (and the cut is recorded)
    concurrency = 16
    cache = "annotate_cache.jsonl"            # relative to the config; keyed by prompt + model + panel text
    lang = "zh"                               # language of summary / reasons (quotes stay verbatim)
    result_facets = ["task_completed"]        # optional extra fields the instructions ask for -> facets ai_<name>

Each issue is an evidence chain of exact quotes, all sharing one note id so the page shows them together:
  requirement -- what the task asks, quoted from the `task_panel` (shown in full at the top of the notes);
  environment -- what the environment / log says that makes it wrong (a tool result, a retrieved record, a rule
                 in the system prompt), quoted from the other panels; only that excerpt is shown;
  behavior    -- the offending model output (message, tool call), quoted from the other panels.
Any of the three may be empty; an issue is kept if at least one quote is found. Each annotated record also gets
a Score(model="AI:<model>", scale="verdict", value=<label>, reason=<summary>, comparable=False).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fairyview.schema import ReviewRecord, Score, Span

PROMPT_VERSION = "annotate-v5"

SYSTEM = """You review one record for a data / model-behaviour audit. You see only the numbered panels below.
For every problem build an evidence chain of EXACT quotes (copy the characters; contiguous substrings; never
translate them; 3-300 characters each):
- "requirement": the part of the TASK that the model fails to satisfy, copied from the task panel;
- "environment": what the environment / log says that shows the model is wrong (a tool result, a retrieved
  email or record, an error message, a rule in the system prompt), copied from the other panels;
- "behavior": the model's own offending output (its message or tool call), copied from the other panels.
Leave a field as "" when it does not apply, but give every quote that exists.
Return only JSON:
{"verdict": "<one short label>", "summary": "<one or two sentences>",
 "issues": [{"reason": "<what the model did, what was required instead, and why that is wrong>",
             "requirement": "...", "environment": "...", "behavior": "...",
             "pattern": "<catalog id if the task instructions give a catalog, else omit>"}],
 ...any extra fields the task instructions ask for}
Return at most 6 issues, the most important first. If nothing is wrong, return an empty "issues" list."""


def _key(cfg: dict) -> str:
    """key_file: JSON ({"OPENAI_API_KEY": ...} or any single field) or a plain-text file holding the key."""
    raw = Path(os.path.expanduser(cfg["key_file"])).read_text().strip()
    if not raw.startswith("{"):
        return raw
    data = json.loads(raw)
    return data.get(cfg.get("key_field", "OPENAI_API_KEY")) or next(iter(data.values()))


class Annotator:
    def __init__(self, cfg: dict, base_dir: Path):
        self.cfg = cfg
        self.model = cfg["model"]
        self.url = cfg.get("base_url", "https://maas.tatucloud.com/v1").rstrip("/") + "/chat/completions"
        self.panels = list(cfg["panels"])
        self.task_panel = cfg.get("task_panel")
        # each target is reviewed on its own, together with the task panel
        self.targets = list(cfg.get("targets") or [None])
        self.max_chars = int(cfg.get("max_chars", 60000))
        self.only = cfg.get("only") or {}
        self.instructions = cfg["instructions"].strip()
        self.cache_path = base_dir / cfg.get("cache", "annotate_cache.jsonl")
        self._secret = _key(cfg)
        self._lock = threading.Lock()
        self.cache = {}
        if self.cache_path.exists():
            for line in self.cache_path.open():
                row = json.loads(line)
                self.cache[row["key"]] = row["result"]
        self.stats = Counter()

    def wanted(self, record: ReviewRecord) -> bool:
        return all(str(record.facets.get(k)) in {str(v) for v in vals} for k, vals in self.only.items())

    def _names(self, target) -> list[str]:
        return self.panels if target is None else [n for n in (self.task_panel, target) if n]

    def _texts(self, record: ReviewRecord, target=None) -> list[tuple[int, str]]:
        by_role = {p.role: i for i, p in enumerate(record.panels)}
        return [(by_role[name], record.panels[by_role[name]].text) for name in self._names(target) if name in by_role]

    def facet(self, name: str, target) -> str:
        return f"ai_{name}" if target in (None, self.targets[0]) else f"ai_{name}_{target}"

    def _cache_key(self, texts: list[str]) -> str:
        h = hashlib.sha256()
        for part in (PROMPT_VERSION, self.model, self.instructions, *texts):
            h.update(part.encode()); h.update(b"\0")
        return h.hexdigest()

    def _ask(self, user: str) -> dict:
        body = {"model": self.model, "temperature": 0, "stream": False,
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
        if self.cfg.get("thinking_disabled"):
            body["thinking"] = {"type": "disabled"}
        if self.cfg.get("max_tokens"):
            body["max_tokens"] = int(self.cfg["max_tokens"])
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._secret}"})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    content = json.load(r)["choices"][0]["message"]["content"] or ""
                start, end = content.find("{"), content.rfind("}")
                return json.loads(content[start:end + 1])
            except (json.JSONDecodeError, ValueError):
                self.stats["bad_json"] += 1
                if attempt == 4:
                    return {"verdict": "unparsed", "summary": "model output was not JSON", "issues": []}
            except Exception as e:  # network / rate limit: back off
                self.stats["retry"] += 1
                if attempt == 4:
                    return {"verdict": "error", "summary": f"request failed: {type(e).__name__}", "issues": []}
                time.sleep(5 * (attempt + 1))

    def result(self, record: ReviewRecord, target=None) -> dict | None:
        texts = [t[: self.max_chars] for _, t in self._texts(record, target)]
        if target is not None and target not in {p.role for p in record.panels}:
            return None
        if not texts:
            return None
        key = self._cache_key(texts)
        if key in self.cache:
            self.stats["cached"] += 1
            return self.cache[key]
        cut = [i + 1 for i, (_, t) in enumerate(self._texts(record, target)) if len(t) > self.max_chars]
        lang = {"zh": "Simplified Chinese", "en": "English"}.get(self.cfg.get("lang", "en"), self.cfg.get("lang"))
        names = [n for n in self._names(target) if n in {p.role for p in record.panels}]
        task_no = names.index(self.task_panel) + 1 if self.task_panel in names else None
        user = (f"Task instructions:\n{self.instructions}\n\n"
                + (f"The task panel is panel {task_no}; quote \"requirement\" from it and the other quotes from the other panels.\n" if task_no else "")
                + f"Write \"summary\" and every \"reason\" in {lang}: say concretely what is wrong and why.\n\n") + "\n\n".join(
            f"=== panel {i + 1}{' (task)' if i + 1 == task_no else ''}{' (truncated)' if i + 1 in cut else ''} ===\n{t}"
            for i, t in enumerate(texts))
        result = self._ask(user)
        self.stats["called"] += 1
        with self._lock:
            self.cache[key] = result
            with self.cache_path.open("a") as f:
                f.write(json.dumps({"key": key, "model": self.model, "prompt_version": PROMPT_VERSION, "result": result},
                                   ensure_ascii=False) + "\n")
        return result

    def apply(self, record: ReviewRecord, result: dict, target=None) -> ReviewRecord:
        order = self._texts(record, target)
        prefix = f"{self.targets.index(target) + 1}." if len(self.targets) > 1 else ""
        task = [(i, t) for i, t in order if record.panels[i].role == self.task_panel]
        rest = [(i, t) for i, t in order if record.panels[i].role != self.task_panel] or order

        def find(quote, where):
            return next(((i, t.find(quote)) for i, t in where if t.find(quote) >= 0), None) if len(quote) >= 3 else None

        # kind per link: requirement = match (yellow), environment = evidence, behavior = warning (red, carries the reason)
        n = 0
        patterns = []
        for issue in result.get("issues") or []:
            reason = str(issue.get("reason") or "").strip()[:400]
            pat = str(issue.get("pattern") or "").strip()[:40]  # optional pattern id from a catalog in the instructions
            sev = str(issue.get("severity") or "").strip()[:10]
            conf = issue.get("confidence")
            conf = "" if conf is None else str(conf)[:8]
            if pat or sev or conf:
                meta = " · ".join(x for x in (pat, sev, conf) if x)
                reason = f"[{meta}] {reason}"
            found = []
            for field, kind, where in (("requirement", "match", task or order), ("environment", "evidence", rest),
                                       ("behavior", "warning", rest)):
                quote = str(issue.get(field) or "").strip()
                if not quote:
                    continue
                hit = find(quote, where)
                self.stats[f"{field}_{'kept' if hit else 'not_found'}"] += 1
                if hit:
                    found.append((hit, quote, kind, field))
            if not found:
                self.stats["issue_dropped"] += 1
                continue
            n += 1
            self.stats["issue_kept"] += 1
            if pat:
                patterns.append(pat)
            for (panel_index, at), quote, kind, field in found:
                record.panels[panel_index].spans.append(Span(
                    start=at, end=at + len(quote), kind=kind, note=f"{prefix}{n}",
                    label=f"AI：{reason}" if field == "behavior" or len(found) == 1 else None))
            if not any(f == "behavior" for *_, f in found) and len(found) > 1:  # keep the reason on some link
                (panel_index, at), quote, kind, field = found[-1]
                record.panels[panel_index].spans[-1].label = f"AI：{reason}"
        # A hard-error verdict without any located quote is not reviewable; downgrade it instead of
        # making the reviewer hunt for evidence the model never produced.
        if str(result.get("verdict", "")) in ("unparsed", "error"):
            result["verdict"] = "other"
            result["summary"] = (str(result.get("summary", "")) + " 解析失败，归入 other。").strip()
        if str(result.get("verdict", "")) == "hard_error" and n == 0:
            result["verdict"] = "uncertain"
            result["summary"] = (str(result.get("summary", "")) + " 证据未定位，降级为 uncertain。").strip()
        where = next((p.label for p in record.panels if p.role == target), "") if target else ""
        record.scores.append(Score(model=f"AI:{self.model}" + (f" · {where}" if where else ""), value=str(result.get("verdict", "")),
                                   scale="verdict", reason=str(result.get("summary", ""))[:500], comparable=False))
        record.facets[self.facet("verdict", target)] = str(result.get("verdict", ""))[:60]
        if patterns:  # every catalog pattern found (kept issues only), so a reviewer can search for one
            joined = " ".join(sorted(set(patterns)))
            record.fields.append([self.facet("patterns", target), joined])
            record.facets[self.facet("patterns", target)] = joined
        for name in self.cfg.get("result_facets") or []:  # extra scalar fields the instructions asked for
            record.facets[self.facet(name, target)] = str(result.get(name))[:60]
        return record


def facet_names(cfg: dict) -> list[str]:
    """Facets the annotation adds, for the page's filter bar."""
    targets = list(cfg.get("targets") or [None])
    names = ["verdict", "patterns", *(cfg.get("result_facets") or [])]
    return [f"ai_{n}" if i == 0 else f"ai_{n}_{t}" for i, t in enumerate(targets) for n in names]


def wrap(records, cfg: dict, base_dir: Path):
    """Annotate the records that pass `only` (each target separately); return them all, plus stats for the manifest."""
    ann = Annotator(cfg, base_dir)
    records = list(records)
    jobs = [(r, t) for r in records if ann.wanted(r) for t in ann.targets]
    with ThreadPoolExecutor(int(cfg.get("concurrency", 16))) as ex:
        results = list(ex.map(lambda job: ann.result(*job), jobs))
    for (record, target), result in zip(jobs, results):
        if result is not None:
            ann.apply(record, result, target)
    for record in records:
        for name in facet_names(cfg):
            record.facets.setdefault(name, "not annotated")
    # annotated records first (stable), so the page opens on what the reviewer came to check
    first = facet_names(cfg)[0]
    records.sort(key=lambda r: r.facets.get(first) == "not annotated")
    stats = dict(ann.stats, annotated=len({id(r) for r, _ in jobs}), reviews=len(jobs), model=ann.model,
                 prompt_version=PROMPT_VERSION)
    return records, stats
