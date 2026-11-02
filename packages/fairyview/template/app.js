/* DataReview client: renders REVIEW_CONFIG + records. No external dependencies. */
(function () {
  "use strict";

  const CFG = window.REVIEW_CONFIG || {};
  const LS_KEY = "datareview:" + (CFG.data_key || CFG.title || "dev");
  const LANG_KEY = "fairyview:lang";

  /* ---------- i18n: every visible string goes through t() ---------- */

  const I18N = {
    en: {
      search: "Search", search_hint: "id / text", view: "View", cards: "Cards", table: "Table",
      layout: "Panel layout", side_by_side: "Side by side", stacked: "Stacked", toggle: "Toggle",
      blind_on: "Hide scores and AI notes, read text first", blind_off: "Show scores",
      storage_note: "Decisions are kept in this browser's localStorage; export them as JSONL below.",
      export: "Export decisions.jsonl", clear: "Clear decisions on this page",
      chars: "chars", decision: "Decision", keep: "Keep", drop: "Drop", unsure: "Unsure",
      marked: "Marked: ", all: "All", records: "records", shown: "showing {n}",
      generated: "generated", source: "Source: ",
      more_files: " and {n} files in total", dropped: "dropped {n} rows ({detail})",
      no_drops: "read {n} rows, none dropped", caveats: "Read this first",
      categories: "Categories", cat_shown: "{n} of {total}", groups: "Groups",
      cat_short: "{cats} categories, {shown} of {total} rows shown",
      joined: "joined {cols} from {n} files on {on}; {miss} rows without a match",
      load_failed: "Failed to load: ",
      notes: "Highlights ({n}) — click to jump",
      issues: "AI findings ({n}) — click an excerpt to jump to it",
      history: "Resolved later ({n}) — kept for audit, not counted as a hard error",
      task_full: "Task (requirements cited by the findings are highlighted)",
      req: "Task requirement", env: "Environment / log evidence", beh: "Model behavior",
      prev: "Prev", next: "Next", jump: "Global #", progress: "#{seq} / {total} · filtered {pos} / {shown}",
    },
    zh: {
      search: "搜索", search_hint: "id / 文本内容", view: "视图", cards: "卡片", table: "表格",
      layout: "面板布局", side_by_side: "并排", stacked: "上下", toggle: "切换",
      blind_on: "隐藏分数和 AI 标注，先看文本", blind_off: "显示分数",
      storage_note: "决策保存在浏览器 localStorage；可用下方按钮导出 JSONL。",
      export: "导出 decisions.jsonl", clear: "清除本页决策",
      chars: "字符", decision: "决策", keep: "保留", drop: "剔除", unsure: "存疑",
      marked: "已标记：", all: "全部", records: "条", shown: "已显示 {n}",
      generated: "生成于", source: "来源：",
      more_files: " 等 {n} 个文件", dropped: "丢弃 {n} 行（{detail}）",
      no_drops: "读取 {n} 行，无丢弃", caveats: "读之前先看",
      categories: "分类", cat_shown: "{n} / {total}", groups: "分组",
      cat_short: "{cats} 个分类，显示 {shown} / {total} 行",
      joined: "按 {on} 从 {n} 个文件关联 {cols}；{miss} 行无匹配",
      load_failed: "加载失败：",
      notes: "高亮标注（{n} 处）· 点击跳转到原文",
      issues: "AI 发现的问题（{n} 个）· 点击原文片段跳转",
      history: "已修复的历史问题（{n} 个）· 不计入硬性错误",
      task_full: "题目原文（被违背的要求已标出）",
      req: "题目要求", env: "环境 / 日志依据", beh: "模型行为",
      prev: "上一页", next: "下一页", jump: "全局序号", progress: "#{seq} / {total} · 筛选内 {pos} / {shown}",
    },
  };

  const CONTROL_DEFAULTS = CFG.default_controls || {};

  function pickLang() {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved && I18N[saved]) return saved;
    if (CONTROL_DEFAULTS.lang && I18N[CONTROL_DEFAULTS.lang]) return CONTROL_DEFAULTS.lang;
    if (CFG.lang && I18N[CFG.lang]) return CFG.lang;
    return (navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en";
  }

  function facetDefaults() {
    const names = new Set(CFG.facets || []);
    const values = {};
    for (const [name, value] of Object.entries(CONTROL_DEFAULTS)) {
      if (names.has(name) && value !== "" && value != null) values[name] = String(value);
    }
    return values;
  }

  let lang = pickLang();

  function t(key, vars) {
    let text = (I18N[lang] && I18N[lang][key]) || I18N.en[key] || key;
    for (const [k, v] of Object.entries(vars || {})) text = text.replace("{" + k + "}", v);
    return text;
  }

  function applyStaticText() {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.placeholder = t(el.dataset.i18nPlaceholder);
    });
    const blind = document.getElementById("blind");
    if (blind) blind.textContent = state.blind ? t("blind_off") : t("blind_on");
  }
  const state = {
    records: [],
    filtered: [],
    search: CONTROL_DEFAULTS.search || "",
    facetValues: facetDefaults(),
    view: CONTROL_DEFAULTS.view || "cards",
    layout: CONTROL_DEFAULTS.layout || CFG.panel_layout || "side_by_side",
    blind: Boolean(CFG.blinded_default),
    decisions: loadDecisions(),
    cursor: 0,
  };

  function esc(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* ---------- data loading ---------- */

  function loadRecords() {
    if (window.REVIEW_RECORDS) return Promise.resolve(window.REVIEW_RECORDS);
    const index = window.REVIEW_SHARD_INDEX;
    if (!index) return Promise.resolve([]);
    // Dynamic <script> injection works under file:// where fetch is blocked.
    const loads = index.shards.map(
      (src, i) =>
        new Promise((resolve, reject) => {
          if (window["REVIEW_SHARD_" + i]) return resolve(window["REVIEW_SHARD_" + i]);
          const tag = document.createElement("script");
          tag.src = src;
          tag.onload = () => resolve(window["REVIEW_SHARD_" + i] || []);
          tag.onerror = () => reject(new Error("failed to load " + src));
          document.head.appendChild(tag);
        })
    );
    return Promise.all(loads).then((chunks) => chunks.flat());
  }

  /* ---------- decisions ---------- */

  function loadDecisions() {
    try {
      return JSON.parse(localStorage.getItem(LS_KEY) || "{}");
    } catch (e) {
      return {};
    }
  }

  function saveDecisions() {
    localStorage.setItem(LS_KEY, JSON.stringify(state.decisions));
  }

  function setDecision(id, value) {
    if (state.decisions[id] === value) delete state.decisions[id];
    else state.decisions[id] = value;
    saveDecisions();
    render();
  }

  /* ---------- span rendering ---------- */

  // The spans a panel actually draws, in text order, with the part each one shows (overlaps are trimmed).
  // renderText and the per-record note list both use it, so note n always points at mark n.
  function visibleSpans(panel) {
    const text = panel.text || "";
    const out = [];
    if (!(panel.spans || []).length) return out;
    // Python spans use Unicode code points; JS slice uses UTF-16 code units.
    let offsets = null;
    if (/[\uD800-\uDBFF]/.test(text)) {
      offsets = [0];
      for (const char of text) offsets.push(offsets[offsets.length - 1] + char.length);
    }
    const unitOffset = (n) => offsets ? offsets[Math.min(n, offsets.length - 1)] : n;
    let cursor = 0;
    for (const span of (panel.spans || []).slice().sort((a, b) => a.start - b.start || b.end - a.end)) {
      const start = Math.max(unitOffset(span.start), cursor);
      const end = Math.min(unitOffset(span.end), text.length);
      if (end <= start) continue;
      out.push({ span, start, end });
      cursor = end;
    }
    return out;
  }

  // Numbered marks: a span with a note (one AI finding cited in several places) is numbered by its note and
  // addressed as data-mark="<note>-<kind>"; a labelled span without a note gets its own running number.
  // inNotes renders a copy (the full task in the findings box) without data-mark, so jumps land in the panels.
  function renderText(panel, counter, inNotes) {
    const text = panel.text || "";
    let html = "";
    let cursor = 0;
    for (const { span, start, end } of visibleSpans(panel)) {
      html += esc(text.slice(cursor, start));
      const label = span.label ? ' title="' + esc(span.label) + '"' : "";
      let num = "", key = "";
      if (span.note) { num = span.note; key = span.note + "-" + span.kind; }
      else if (span.label) { num = String(++counter.n); key = "x" + num; }
      const tag = num ? '<sup class="mark-num">' + esc(num) + "</sup>" : "";
      const statusClass = span.status === "resolved_later" ? " k-history" : "";
      html += '<mark class="k-' + esc(span.kind) + statusClass + '"' + label + (key && !inNotes ? ' data-mark="' + esc(key) + '"' : "") + ">" +
        tag + esc(text.slice(start, end)) + "</mark>";
      cursor = end;
    }
    html += esc(text.slice(cursor));
    return html;
  }

  function snippetOf(text, start, end) {
    const s = text.slice(start, end);
    return s.length > 240 ? s.slice(0, 240) + "…" : s;
  }

  function renderNotes(record) {
    const panels = record.panels || [];
    const groups = new Map();
    for (const finding of record.findings || []) {
      groups.set(finding.note, { reason: finding.label, links: [], status: finding.status || "confirmed",
        locations: finding.locations || [] });
    }
    panels.forEach((p) => {
      for (const { span, start, end } of visibleSpans(p)) {
        if (!span.note) continue;
        if (!groups.has(span.note)) groups.set(span.note, { reason: "", links: [], status: "confirmed" });
        const g = groups.get(span.note);
        if (span.status === "resolved_later") g.status = "resolved_later";
        if (span.label && !g.reason) g.reason = span.label;
        g.links.push({ kind: span.kind, text: snippetOf(p.text || "", start, end), panel: p.label });
      }
    });

    const order = { match: 0, evidence: 1, warning: 2 };
    const names = { match: t("req"), evidence: t("env"), warning: t("beh") };
    function renderGroupItems(entries) {
      return entries.map(([note, g]) => {
        const links = g.links.slice().sort((a, b) => (order[a.kind] ?? 9) - (order[b.kind] ?? 9)).map((l) =>
          l.kind === "match"
            ? '<div class="link k-' + esc(l.kind) + '"><span class="link-kind">' + esc(names[l.kind]) + "</span>「" + esc(l.text) + "」</div>"
            : '<button type="button" class="link k-' + esc(l.kind) + '" data-jump="' + esc(note + "-" + l.kind) + '">' +
              '<span class="link-kind">' + esc(names[l.kind] || l.kind) + '</span><span class="note-where">' + esc(l.panel) + "</span>" +
              '<span class="note-snippet">' + esc(l.text) + "</span></button>").join("");
        return '<li class="issue' + (g.status === "resolved_later" ? " issue-history" : "") + '"><div class="issue-head"><span class="note-num">' + esc(note) + "</span>" +
          '<span class="note-label">' + esc(g.reason) + "</span></div>" +
          (g.locations || []).map((location) => '<div class="note-where">' + esc(location) + '</div>').join("") +
          links + "</li>";
      });
    }
    function statusEntries(status) {
      return [...groups.entries()].filter(([, g]) => g.status === status);
    }

    let html = "";
    const active = statusEntries("confirmed");
    if (active.length) {
      const taskPanels = panels.filter((p) => (p.spans || []).some((sp) => sp.note && sp.kind === "match"));
      const task = taskPanels.map((p) =>
        '<div class="task-full"><div class="task-head">' + esc(t("task_full")) + " · " + esc(p.label) + "</div><pre>" +
        renderText(p, { n: 0 }, true) + "</pre></div>").join("");
      html += '<details class="notes" open><summary>' + esc(t("issues", { n: active.length })) + "</summary>" +
        "<ol>" + renderGroupItems(active).join("") + "</ol>" + task + "</details>";
    }
    const history = statusEntries("resolved_later");
    if (history.length) {
      html += '<details class="notes history"><summary>' + esc(t("history", { n: history.length })) + "</summary>" +
        "<ol>" + renderGroupItems(history).join("") + "</ol></details>";
    }

    const items = [];
    let n = 0;
    for (const p of panels) {
      const text = p.text || "";
      for (const { span, start, end } of visibleSpans(p)) {
        if (span.note || !span.label) continue;
        n += 1;
        items.push(
          '<li><button type="button" class="note k-' + esc(span.kind) + '" data-jump="x' + n + '">' +
          '<span class="note-num">' + n + "</span>" +
          '<span class="note-label">' + esc(span.label) + "</span>" +
          '<span class="note-where">' + esc(p.label) + "</span>" +
          '<span class="note-snippet">' + esc(snippetOf(text, start, end)) + "</span></button></li>");
      }
    }
    if (items.length) html += '<details class="notes" open><summary>' + esc(t("notes", { n: items.length })) + "</summary><ol>" +
      items.join("") + "</ol></details>";
    return html;
  }

  /* ---------- scores ---------- */

  function renderScores(record) {
    if (!record.scores || !record.scores.length) return "";
    const items = record.scores.map((s) => {
      const scaleClass = "scale-" + String(s.scale || "0-1").replace(/[^0-9a-z.-]/gi, "-");
      const incomparable = s.comparable === false ? " incomparable" : "";
      let bar = "";
      if (typeof s.value === "number") {
        const max = s.scale === "1-5" ? 5 : 1;
        const pct = Math.max(0, Math.min(100, (100 * s.value) / max));
        bar = '<div class="bar"><i style="width:' + pct.toFixed(2) + '%"></i></div>';
      }
      const reason = s.reason ? '<div class="reason">' + esc(s.reason) + "</div>" : "";
      const shown = typeof s.value === "number" ? s.value.toFixed(s.scale === "1-5" ? 0 : 4) : esc(s.value);
      return (
        '<div class="score ' + scaleClass + incomparable + '"><b>' +
        esc(s.model) + ": " + shown + (s.scale === "1-5" ? " / 5" : "") +
        "</b>" + bar + reason + "</div>"
      );
    });
    return '<div class="scores">' + items.join("") + "</div>";
  }

  /* ---------- record rendering ---------- */

  function renderFields(record) {
    if (!record.fields || !record.fields.length) return "";
    const items = record.fields
      .filter(([, v]) => v !== null && v !== undefined && v !== "")
      .map(([k, v]) => "<span><b>" + esc(k) + "</b>: " + esc(typeof v === "object" ? JSON.stringify(v) : v) + "</span>");
    return '<div class="fields">' + items.join("") + "</div>";
  }

  function renderPanels(record) {
    if (!record.panels || !record.panels.length) return "";
    const tabs =
      state.layout === "toggle" && record.panels.length > 1
        ? '<div class="toggle-tabs">' +
          record.panels
            .map((p, i) => '<button type="button" data-toggle="' + i + '">' + esc(p.label) + "</button>")
            .join("") +
          "</div>"
        : "";
    const counter = { n: 0 };
    const groups = new Map();
    record.panels.forEach((p, i) => {
      const key = p.group || "panel-" + i;
      if (!groups.has(key)) groups.set(key, { label: p.group_label, collapsed: p.group_collapsed, panels: [] });
      const heading = '<span>' + esc(p.label) + '</span><span>' +
        (p.text || "").length.toLocaleString() + " " + t("chars") + '</span>';
      const content = '<pre>' + renderText(p, counter) + '</pre>';
      const body = p.group
        ? '<details' + (p.collapsed ? '' : ' open') + '><summary>' + heading + '</summary>' + content + '</details>'
        : '<h4>' + heading + '</h4>' + content;
      groups.get(key).panels.push('<div class="panel" data-role="' + esc(p.role) + '" data-panel="' + i + '"' +
        (state.layout === "toggle" && i > 0 ? " hidden" : "") + '>' + body + '</div>');
    });
    const html = [...groups.values()].map((g) => g.label
      ? '<details class="message-group"' + (g.collapsed ? '' : ' open') + '><summary>' + esc(g.label) +
        '</summary>' + g.panels.join('') + '</details>'
      : g.panels.join('')).join('');
    return tabs + '<div class="panels ' + esc(state.layout) + '">' + html + '</div>';
  }

  function renderDecision(record) {
    const current = state.decisions[record.id];
    const btn = (value, label, cls) =>
      '<button type="button" data-decide="' + value + '" class="' + (current === value ? cls : "") + '">' + label + "</button>";
    return (
      '<div class="decision"><span class="small">' + t("decision") + "</span>" +
      btn("keep", t("keep"), "sel-keep") + btn("drop", t("drop"), "sel-drop") + btn("unsure", t("unsure"), "sel-unsure") +
      (current ? '<span class="small">' + t("marked") + esc(t(current)) + "</span>" : "") +
      "</div>"
    );
  }

  function renderCard(record) {
    const badges = Object.entries(record.facets || {})
      .map(([k, v]) => '<span class="badge">' + esc(k) + "=" + esc(v) + "</span>")
      .join("");
    const notes = renderNotes(record);
    return (
      '<article class="record' + (notes ? " has-notes" : "") + '" id="rec-' + esc(record.id) + '" data-id="' + esc(record.id) + '">' +
      '<div class="record-head"><h3><span class="seq">#' + esc(record._seq) + '</span> · ' + esc(record.id) + '</h3><div class="badges">' + badges + "</div></div>" +
      renderFields(record) +
      renderScores(record) +
      notes +
      renderPanels(record) +
      renderDecision(record) +
      "</article>"
    );
  }

  function renderTable(rows) {
    const head =
      "<tr><th>id</th><th>facets</th><th>text</th><th>" + t("decision") + "</th></tr>";
    const body = rows
      .map((r) => {
        const text = (r.panels && r.panels[0] ? r.panels[0].text : "").slice(0, 400);
        const facets = Object.entries(r.facets || {}).map(([k, v]) => k + "=" + v).join(" · ");
        return (
          "<tr><td>" + esc(r.id) + "</td><td>" + esc(facets) + '</td><td class="text"><div>' + esc(text) +
          "</div></td><td>" + esc(state.decisions[r.id] || "") + "</td></tr>"
        );
      })
      .join("");
    return '<table class="records"><thead>' + head + "</thead><tbody>" + body + "</tbody></table>";
  }

  /* ---------- filtering ---------- */

  const FACET_LABELS = {
    visual_class: "视觉类型", source: "来源", tier: "筛选档", warning: "完整性警告",
    rules: "规则版本", model_purity: "模型纯度", lang: "语言",
    ai_verdict: "AI 结论", ai_patterns: "错误类型", ai_severity: "严重度", ai_confidence: "置信度",
    text_only_safe: "纯文本安全",
  };

  function matches(record) {
    if (state.search) {
      const hay = (record.id + " " + (record.panels || []).map((p) => p.text).join(" ")).toLowerCase();
      if (!hay.includes(state.search)) return false;
    }
    for (const [name, value] of Object.entries(state.facetValues)) {
      if (!value) continue;
      const raw = String(record.facets ? record.facets[name] : "");
      if (name === "ai_patterns") {
        if (!raw.split(/\s+/).includes(value)) return false;
      } else if (raw !== value) return false;
    }
    return true;
  }

  function facetValues() {
    const values = {};
    for (const name of CFG.facets || []) {
      const seen = new Set();
      for (const record of state.records) {
        const v = record.facets ? record.facets[name] : undefined;
        if (v === undefined || v === null) continue;
        if (name === "ai_patterns") {
          for (const token of String(v).split(/\s+/)) {
            if (token && token !== "not" && token !== "annotated") seen.add(token);
          }
        } else {
          seen.add(String(v));
        }
      }
      values[name] = Array.from(seen).sort();
    }
    return values;
  }

  function renderFacetControls() {
    const host = document.getElementById("facets");
    if (!host) return;
    const values = facetValues();
    host.innerHTML = Object.entries(values)
      .filter(([, list]) => list.length > 1 && list.length <= 40)
      .map(([name, list]) => {
        const opts = ['<option value="">' + t("all") + "</option>"]
          .concat(list.map((v) => '<option value="' + esc(v) + '">' + esc(v) + "</option>"))
          .join("");
        return '<label class="small">' + esc(FACET_LABELS[name] || name) + ' <select data-facet="' + esc(name) + '">' + opts + "</select></label>";
      })
      .join("");
    host.querySelectorAll("select[data-facet]").forEach((sel) => {
      sel.value = state.facetValues[sel.dataset.facet] || "";
      sel.addEventListener("change", () => {
        state.facetValues[sel.dataset.facet] = sel.value;
        render(true);
      });
    });
  }

  /* ---------- render ---------- */

  function render(reset) {
    state.filtered = state.records.filter(matches);
    if (reset) state.cursor = 0;
    if (state.cursor >= state.filtered.length) state.cursor = Math.max(0, state.filtered.length - 1);
    const current = state.filtered[state.cursor];
    const host = document.getElementById("records");
    host.innerHTML = current ? (state.view === "table" ? renderTable([current]) : renderCard(current)) : "";
    updatePager(current);
    document.body.classList.toggle("blind", state.blind);
  }

  function updatePager(current) {
    const count = document.getElementById("count");
    if (count) count.textContent = state.filtered.length + " / " + state.records.length + " " + t("records");
    const progress = document.getElementById("progress");
    const bar = document.getElementById("progressbar");
    const seqInput = document.getElementById("seq");
    const prev = document.getElementById("prev");
    const next = document.getElementById("next");
    const total = state.records.length;
    if (current) {
      if (seqInput) { seqInput.max = String(total); seqInput.value = String(current._seq); }
      if (progress) progress.textContent = t("progress", { seq: current._seq, total, pos: state.cursor + 1, shown: state.filtered.length });
      if (bar) bar.style.width = (100 * (state.cursor + 1) / Math.max(1, state.filtered.length)) + "%";
    } else {
      if (progress) progress.textContent = "0 / " + total;
      if (bar) bar.style.width = "0%";
    }
    if (prev) prev.disabled = state.cursor <= 0;
    if (next) next.disabled = state.cursor >= state.filtered.length - 1;
  }

  function scrollToRecord() {
    const el = document.getElementById("records");
    if (el) window.scrollTo(0, Math.max(0, el.offsetTop - 8));
  }

  function jumpToSeq(value) {
    const n = Number(value);
    const rec = state.records.find((r) => r._seq === n);
    if (!rec) return;
    let pos = state.filtered.indexOf(rec);
    if (pos < 0) {
      state.search = "";
      state.facetValues = {};
      const search = document.getElementById("search");
      if (search) search.value = "";
      renderFacetControls();
      state.filtered = state.records.slice();
      pos = state.filtered.indexOf(rec);
    }
    state.cursor = Math.max(0, pos);
    render();
    scrollToRecord();
  }

  function bindControls() {
    const search = document.getElementById("search");
    if (search) search.value = state.search;
    let searchTimer = null;
    search.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.search = search.value.trim().toLowerCase();
        render(true);
      }, 150);
    });
    const view = document.getElementById("view");
    view.value = state.view;
    view.addEventListener("change", () => {
      state.view = view.value;
      render(true);
    });
    const layout = document.getElementById("layout");
    layout.value = state.layout;
    layout.addEventListener("change", () => {
      state.layout = layout.value;
      render();
    });
    const blind = document.getElementById("blind");
    blind.addEventListener("click", () => {
      state.blind = !state.blind;
      applyStaticText();
      render();
    });
    const langSelect = document.getElementById("lang");
    if (langSelect) {
      langSelect.value = lang;
      langSelect.addEventListener("change", () => {
        lang = langSelect.value;
        localStorage.setItem(LANG_KEY, lang);
        applyStaticText();
        renderHeader();
        renderFacetControls();
        render();
      });
    }
    document.getElementById("records").addEventListener("click", (event) => {
      const decide = event.target.closest("[data-decide]");
      if (decide) {
        const article = decide.closest("article");
        const id = article ? article.dataset.id : decide.dataset.id;
        if (id) setDecision(id, decide.dataset.decide);
        return;
      }
      const jump = event.target.closest("[data-jump]");
      if (jump) {
        const article = jump.closest("article");
        const mark = article && article.querySelector('mark[data-mark="' + jump.dataset.jump + '"]');
        if (mark) {
          for (let parent = mark.parentElement; parent; parent = parent.parentElement) {
            if (parent.tagName === "DETAILS") parent.open = true;
          }
          const panel = mark.closest(".panel");
          if (panel && panel.hidden) {  // toggle layout: show the panel that holds the mark
            article.querySelectorAll(".panel").forEach((p) => { p.hidden = p !== panel; });
          }
          const pre = mark.closest("pre");
          if (pre) pre.scrollTop += mark.getBoundingClientRect().top - pre.getBoundingClientRect().top - pre.clientHeight / 3;
          mark.scrollIntoView({ block: "nearest", behavior: "smooth" });
          mark.classList.remove("flash");
          void mark.offsetWidth;  // restart the animation on repeated clicks
          mark.classList.add("flash");
        }
        return;
      }
      const toggle = event.target.closest("[data-toggle]");
      if (toggle) {
        const index = Number(toggle.dataset.toggle);
        const panels = toggle.closest("article").querySelectorAll(".panel");
        panels.forEach((p) => {
          p.hidden = Number(p.dataset.panel) !== index;
        });
      }
    });
    const prev = document.getElementById("prev");
    if (prev) prev.addEventListener("click", () => {
      if (state.cursor > 0) { state.cursor -= 1; render(); scrollToRecord(); }
    });
    const next = document.getElementById("next");
    if (next) next.addEventListener("click", () => {
      if (state.cursor < state.filtered.length - 1) { state.cursor += 1; render(); scrollToRecord(); }
    });
    const seqInput = document.getElementById("seq");
    if (seqInput) {
      seqInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); jumpToSeq(seqInput.value); }
      });
      seqInput.addEventListener("change", () => jumpToSeq(seqInput.value));
    }
    document.getElementById("export").addEventListener("click", () => {
      const lines = Object.entries(state.decisions).map(([id, decision]) =>
        JSON.stringify({ id, decision, config_hash: CFG.config_hash })
      );
      const blob = new Blob([lines.join("\n") + "\n"], { type: "application/jsonl" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "decisions.jsonl";
      a.click();
      URL.revokeObjectURL(a.href);
    });
    document.getElementById("clear").addEventListener("click", () => {
      state.decisions = {};
      saveDecisions();
      render();
    });
  }

  function renderHeader() {
    const meta = document.getElementById("meta");
    meta.textContent =
      "config " + (CFG.config_hash || "-") + " · " + (CFG.record_count || state.records.length) +
      " " + t("records") + " · " + t("generated") + " " + (CFG.generated_at || "-") + " · schema v" + (CFG.schema_version || "-");
    document.getElementById("description").textContent = CFG.description || "";

    // Provenance first: what file this page came from, and what was dropped.
    // A page that hides either is not reviewable.
    const files = CFG.source_files || [];
    const dropped = CFG.dropped || {};
    const dropTotal = Object.values(dropped).reduce((a, b) => a + b, 0);
    const bits = [];
    if (files.length) {
      const names = files.map((f) => f.path + (f.bytes != null ? " (" + f.bytes + " B)" : ""));
      bits.push(t("source") + names.slice(0, 3).join(", ") + (names.length > 3 ? t("more_files", { n: names.length }) : ""));
    }
    if (dropTotal) {
      const detail = Object.entries(dropped).map(([k, v]) => k + "=" + v).join(", ");
      bits.push(t("dropped", { n: dropTotal, detail: detail }));
    } else if (CFG.rows_examined != null) {
      bits.push(t("no_drops", { n: CFG.rows_examined }));
    }
    if (CFG.join) {
      bits.push(t("joined", {
        cols: CFG.join.columns.join(", "), n: CFG.join.files.length, on: CFG.join.on, miss: CFG.join.unmatched,
      }));
    }
    renderCategories();

    const prov = document.getElementById("provenance");
    if (prov && bits.length) {
      prov.hidden = false;
      prov.textContent = bits.join(" · ");
      if (dropTotal) prov.className = "warning";
    }
    const caveats = CFG.caveats || [];
    const box = document.getElementById("caveats");
    if (caveats.length) {
      box.hidden = false;
      box.innerHTML = "<b>" + t("caveats") + "</b><ul>" + caveats.map((c) => "<li>" + esc(c) + "</li>").join("") + "</ul>";
    }
  }

  /* ---------- categories ---------- */

  // Totals come from the scan, not from the records: a sampled page must say
  // how much of each category exists, or a thin category reads as a small one.
  function renderCategories() {
    const box = document.getElementById("categories");
    const info = CFG.categories;
    if (!box || !info || !info.rows) return;
    const names = Object.keys(info.rows).sort();
    const total = names.reduce((a, n) => a + info.rows[n], 0);
    const shown = names.reduce((a, n) => a + (info.shown[n] || 0), 0);
    const rows = names
      .map((n) => {
        const got = info.shown[n] || 0;
        const all = info.rows[n];
        return "<tr><td>" + esc(n) + "</td><td>" + esc(t("cat_shown", { n: got, total: all })) + "</td></tr>";
      })
      .join("");
    const groups = Object.entries(info.groups || {})
      .map(([g, n]) => "<span class=\"badge\">" + esc(g) + "=" + n + "</span>")
      .join(" ");
    box.hidden = false;
    box.innerHTML =
      "<summary>" + esc(t("cat_short", { cats: names.length, shown: shown, total: total })) + "</summary>" +
      (groups ? "<p>" + esc(t("groups")) + " " + groups + "</p>" : "") +
      '<table class="records"><tbody>' + rows + "</tbody></table>";
  }

  loadRecords()
    .then((records) => {
      records.forEach((r, i) => { r._seq = i + 1; });
      state.records = records;
      applyStaticText();
      renderHeader();
      renderFacetControls();
      bindControls();
      render();
    })
    .catch((err) => {
      document.getElementById("records").innerHTML =
        '<p class="warning">' + t("load_failed") + esc(err.message) + "</p>";
    });
})();
