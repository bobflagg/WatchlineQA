// browser_checks.js: paste into the Browser pane's javascript_tool (action javascript_exec) on the built page.
// Serve the page over http first (python3 -m http.server) and open it with a fresh URL (add ?v=N), because a
// hash-only navigation does not reload. If the pane is hidden the viewport reads 0 wide: show it or resize it.
// Returns a summary. "problems" must be empty.
(async () => {
  await new Promise(r => setTimeout(r, 800));
  const problems = [], info = {};
  info.viewport = [innerWidth, document.documentElement.clientWidth];
  if (!document.documentElement.clientWidth) problems.push("viewport is 0 wide: the pane is hidden");
  const ids = Object.keys(D);
  info.boxes = ids.length; info.snippets = Object.keys(SN).length;

  // 1. every box on every map is clickable and has details; every detail is on a map
  const onMap = [...document.querySelectorAll(".n")].map(n => n.dataset.id);
  ids.forEach(id => { if (!onMap.includes(id)) problems.push("detail without a map box: " + id); });
  onMap.forEach(id => { if (!D[id]) problems.push("map box without details: " + id); });

  // 2. SVG markers resolve (a marker defined in a hidden SVG does not render)
  document.querySelectorAll("[marker-end]").forEach(e => {
    const m = e.getAttribute("marker-end").slice(5, -1);
    if (!document.getElementById(m) || !e.closest("svg").contains(document.getElementById(m))) problems.push("marker not defined in its own svg: " + m);
  });

  // 3. annotation and code tabs for every box
  for (const id of ids) {
    tab = "note"; show(id, false);
    if (!panel.querySelector(".lede")) problems.push("annotation did not render: " + id);
    if (D[id].widget && !panel.querySelector(".wbody").innerHTML.trim()) problems.push("widget empty: " + id);
    if (!hasCode(id) && !hasEv(id)) { if (panel.querySelector(".ptabs")) problems.push("tabs without code or evidence: " + id); continue; }
    if (hasEv(id)) {                                  // release-evidence tab: tables render verbatim and fit
      tab = "ev"; show(id, false);
      const e = D[id].evidence, figs = panel.querySelectorAll(".ex");
      if (!panel.querySelector(".ev-tables")) problems.push("evidence tables did not render: " + id);
      if (figs.length !== (e.examples || []).length) problems.push(`${id}: ${figs.length} example tables for ${(e.examples || []).length}`);
      figs.forEach((fig, k) => {
        const x = e.examples[k], rows = fig.querySelectorAll(".etbl .tr");
        if (rows.length !== x.rows.length + 1) problems.push(`${id}/${x.table}: ${rows.length - 1} rows for ${x.rows.length}`);
        const cells = [...fig.querySelectorAll(".etbl .tr:not(.th) span")].map(c => c.textContent).join("\u0001");
        if (cells !== x.rows.flat().join("\u0001")) problems.push(`${id}/${x.table}: rendered cells differ from the release rows`);
        const t = fig.querySelector(".etbl");
        if (t.scrollWidth > t.clientWidth + 1) problems.push(`${id}/${x.table}: table scrolls sideways`);
      });
      if (panel.scrollWidth > panel.clientWidth + 1) problems.push("panel scrolls sideways on evidence: " + id);
      info.evidence = (info.evidence || 0) + 1;
    }
    if (!hasCode(id)) continue;
    tab = "code"; show(id, false);
    panel.querySelectorAll(".snip").forEach((fig, k) => {
      const s = SN[CODE[id][k]], src = fig.querySelector(".src");
      const rows = fig.querySelectorAll(".ln").length, want = s.code.split("\n").length;
      if (rows !== want) problems.push(`${id}/${CODE[id][k]}: ${rows} rows for ${want} lines`);
      if (src.scrollWidth > src.clientWidth + 1) problems.push(`${id}/${CODE[id][k]}: code scrolls sideways`);
      const text = [...fig.querySelectorAll(".tx")].map(e => e.textContent).join("\n");
      if (text.replace(/\s+/g, "") !== s.code.replace(/\s+/g, "")) problems.push(`${id}/${CODE[id][k]}: rendered text differs from source`);
    });
  }
  tab = "note";

  // 4. view tabs switch, and the page itself never scrolls sideways
  for (const v of SPEC.views) {
    document.getElementById("tab-" + v.id).click();
    if (document.getElementById("view-" + v.id).hidden) problems.push("view did not open: " + v.id);
  }
  show(SPEC.default_node, false);
  if (document.documentElement.scrollWidth > document.documentElement.clientWidth) problems.push("page scrolls sideways");
  info.hljs = typeof window.hljs;
  if (info.hljs !== "object") problems.push("highlight.js did not load (code will be unhighlighted)");
  return {problems, info};
})()
