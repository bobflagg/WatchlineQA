#!/usr/bin/env python3
"""build.py: turn a spec (JSON) into an interactive pipeline explainer.

    python3 build.py spec.json out.html [--local preview.html]

out.html is a page FRAGMENT (a <title>, a <style>, markup and scripts, no <html>/<body>) ready for the
Artifact tool. --local also writes a full page you can serve and open in a browser to check it.

The builder does the mechanical work so the content stays honest:
  * pulls every code snippet VERBATIM from git at a pinned commit (git show SHA:path), and checks the
    line range is real, the edges are not blank, and the commit is on a remote (so permalinks resolve);
  * checks notebook excerpts against the committed notebook's code cells;
  * lays out the SVG maps (a "flow" layout for linear pipelines, a "manual" layout for flowcharts);
  * validates ids, edges, snippet and widget references, and estimates whether box text fits.

Exit status is 1 if any error is found. Warnings do not fail the build. Stdlib only.
See ../references/spec-format.md for the spec.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html as _html
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

KINDS = ["det", "ml", "warn", "io", "rem"]
KIND_LABELS = {"det": "Rule", "ml": "Learned model", "warn": "Lower-confidence stage",
               "io": "Data / no join", "rem": "Result"}
LABELS = {"what": "What it does", "nums": "Example", "measured": "Measured", "open": "Open / fragile",
          "tab_note": "Annotation", "tab_code": "Code", "tab_evidence": "Release evidence",
          "ev_recorded": "What is recorded", "ev_tables": "Where it is stored", "ev_rows": "Real rows",
          "ev_limits": "What it cannot tell you"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

ERRORS: list[str] = []
WARNINGS: list[str] = []


def err(msg: str) -> None:
    ERRORS.append(msg)


def warn(msg: str) -> None:
    WARNINGS.append(msg)


def esc(s) -> str:
    return _html.escape(str(s), quote=True)


# ---------------------------------------------------------------- git snippets

def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True, stderr=subprocess.STDOUT)


def resolve_repos(spec: dict) -> dict:
    repos = {}
    for key, r in (spec.get("repos") or {}).items():
        path = Path(r["path"]).expanduser()
        if not (path / ".git").exists() and not (path / "HEAD").exists():
            err(f"repo {key}: {path} is not a git repository")
            continue
        try:
            sha = git(path, "rev-parse", r["sha"]).strip()
        except subprocess.CalledProcessError as e:
            err(f"repo {key}: cannot resolve {r['sha']}: {e.output.strip()}")
            continue
        try:
            remote = git(path, "branch", "-r", "--contains", sha).strip()
        except subprocess.CalledProcessError:
            remote = ""
        if not remote:
            warn(f"repo {key}: commit {sha[:7]} is not on any remote branch; GitHub permalinks 404 until it is pushed")
        repos[key] = {"path": path, "sha": sha, "slug": r["slug"], "label": r.get("label", key)}
    return repos


def build_snippets(spec: dict, repos: dict) -> dict:
    out = {}
    for sid, s in (spec.get("snippets") or {}).items():
        rk = s.get("repo")
        if rk not in repos:
            err(f"snippet {sid}: unknown repo {rk!r}")
            continue
        r = repos[rk]
        base = f"https://github.com/{r['slug']}/blob/{r['sha']}/"
        name = s["path"].split("/")[-1]
        try:
            raw = git(r["path"], "show", f"{r['sha']}:{s['path']}")
        except subprocess.CalledProcessError:
            err(f"snippet {sid}: {s['path']} not found at {r['sha'][:7]}")
            continue
        if "lines" in s:                                   # notebook (or any file) excerpt by exact lines
            text = raw
            if s["path"].endswith(".ipynb"):
                nb = json.loads(raw)
                text = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
            for line in s["lines"]:
                if line not in text:
                    err(f"snippet {sid}: line not found in {name}: {line[:70]!r}")
            out[sid] = dict(a=0, b=0, lang=s.get("lang", "python"), caption=s["caption"],
                            code="\n".join(s["lines"]), url=base + s["path"], label=f"{r['label']} {name}")
            continue
        lines = raw.split("\n")
        if "start" in s:                                   # locate by text so a drifting line number cannot break it
            hits = [i for i, l in enumerate(lines) if l.startswith(s["start"])]
            if not hits:
                err(f"snippet {sid}: start text not found in {name}: {s['start'][:60]!r}")
                continue
            i0 = hits[min(int(s.get("occurrence", 1)), len(hits)) - 1]
            if "count" in s:
                a, b = i0 + 1, i0 + int(s["count"])
            elif "end" in s:
                j = next((j for j in range(i0, len(lines)) if lines[j].startswith(s["end"])), None)
                if j is None:
                    err(f"snippet {sid}: end text not found after the start in {name}: {s['end'][:60]!r}")
                    continue
                a, b = i0 + 1, j + 1
            else:
                err(f"snippet {sid}: 'start' needs 'count' or 'end'")
                continue
        else:
            a, b = int(s["a"]), int(s["b"])
        if not (1 <= a <= b <= len(lines)):
            err(f"snippet {sid}: lines {a}-{b} outside {name} ({len(lines)} lines)")
            continue
        seg = lines[a - 1:b]
        if not seg[0].strip() or not seg[-1].strip():
            err(f"snippet {sid}: {name}:{a}-{b} starts or ends on a blank line")
        out[sid] = dict(a=a, b=b, lang=s.get("lang", "python"), caption=s["caption"],
                        code=textwrap.dedent("\n".join(seg)),
                        url=base + s["path"] + (f"#L{a}-L{b}" if a != b else f"#L{a}"),
                        label=f"{r['label']} {name}:{a}" + (f"–{b}" if a != b else ""))
    return out


# ---------------------------------------------------------------- release data

class Release:
    """A release directory (CSV tables + manifest.json). Every table that is read is checked against the
    sha256 the manifest records for it, so a quoted row is a row of that release."""

    def __init__(self, key: str, r: dict):
        self.key, self.label, self.url = key, r.get("label", key), r.get("url", "")
        self.path = Path(r["path"]).expanduser()
        self.cache: dict[str, list[dict]] = {}
        self.ok = (self.path / "manifest.json").exists()
        if not self.ok:
            err(f"release {key}: {self.path}/manifest.json not found")
            return
        self.manifest = json.loads((self.path / "manifest.json").read_text())
        self.run = self.manifest.get("run_id", "")

    def table(self, name: str) -> list[dict]:
        if name in self.cache:
            return self.cache[name]
        f = self.path / f"{name}.csv"
        if not f.exists():
            err(f"release {self.key}: no table {name}")
            self.cache[name] = []
            return []
        want = (self.manifest.get("output_checksums") or {}).get(f"{name}.csv")
        got = hashlib.sha256(f.read_bytes()).hexdigest()
        if want != got:
            err(f"release {self.key}: {name}.csv does not match the manifest's checksum")
        with open(f, newline="") as fh:
            self.cache[name] = list(csv.DictReader(fh))
        return self.cache[name]


def resolve_examples(nid: str, ev: dict, releases: dict) -> list[dict]:
    """Turn each example spec ({release, table, where, cols, limit}) into verbatim rows."""
    out = []
    for i, ex in enumerate(ev.get("examples") or []):
        where = f"node {nid} example {i + 1}"
        rk = ex.get("release")
        if rk not in releases or not releases[rk].ok:
            err(f"{where}: unknown release {rk!r}")
            continue
        rel = releases[rk]
        if ex["table"] == "manifest":
            m = rel.manifest
            def dig(d, key):
                for part in key.split("."):
                    d = d[part]
                return d
            try:
                rows = [{"field": k, "value": json.dumps(dig(m, k)) if not isinstance(dig(m, k), str) else dig(m, k)}
                        for k in ex["fields"]]
            except (KeyError, TypeError) as e:
                err(f"{where}: manifest has no field {e}")
                continue
            out.append({"table": "manifest.json", "caption": ex["caption"], "cols": ["field", "value"], "total": len(rows),
                        "rows": [[r["field"], r["value"]] for r in rows],
                        "source": f"{rel.label}, run {rel.run}", "url": rel.url, "note": ex.get("note", "")})
            continue
        rows = rel.table(ex["table"])
        if rows and any(c not in rows[0] for c in ex["cols"]):
            err(f"{where}: {ex['table']} has no column among {ex['cols']}")
            continue
        hit = [r for r in rows if all((r[k] in v) if isinstance(v, list) else (r[k] == v) for k, v in (ex.get("where") or {}).items())]
        if "order_by" in ex:
            hit.sort(key=lambda r: tuple(r[c] for c in ex["order_by"]))
        if not hit:
            err(f"{where}: no rows of {ex['table']} match {ex.get('where')}")
            continue
        shown = hit[: int(ex.get("limit", 6))]
        cols = list(ex["cols"])
        shown = [dict(r) for r in shown]
        placed: dict[str, int] = {}                        # columns already added after each shown column
        for lk in ex.get("lookups") or []:                 # a name beside an id, from a table of the same release
            if lk["col"] not in cols:
                err(f"{where}: lookup column {lk['col']!r} is not shown")
                continue
            ref = rel.table(lk["table"])
            if ref and any(c not in ref[0] for c in (lk["key"], *lk["take"])):
                err(f"{where}: {lk['table']} has no column among {[lk['key'], *lk['take']]}")
                continue
            by = {}
            for row in ref:
                by.setdefault(row[lk["key"]], row)
            at = cols.index(lk["col"]) + 1 + placed.get(lk["col"], 0)
            labels = lk.get("as") or lk["take"]
            groups = [lk["take"]] if lk.get("merge") else [[t] for t in lk["take"]]     # merge: one column from several
            placed[lk["col"]] = placed.get(lk["col"], 0) + len(groups)
            for i, group in enumerate(groups):
                cols.insert(at + i, labels[i])
                for r in shown:
                    src = by.get(r[lk["col"]])
                    r[labels[i]] = " ".join(src[t] for t in group if src and src[t]) if src else ""
        out.append({"table": ex["table"], "caption": ex["caption"], "cols": cols, "total": len(hit),
                    "rows": [[(r[c] or "") for c in cols] for r in shown],
                    "source": f"{rel.label}, run {rel.run}", "url": rel.url, "note": ex.get("note", "")})
    return out


# ---------------------------------------------------------------- svg

def marker(mid: str) -> str:
    return (f'<defs><marker id="{mid}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" stroke="var(--io)" stroke-width="1.5" '
            f'stroke-linecap="round" stroke-linejoin="round"/></marker></defs>')


def fit_check(nid: str, title: str, subs: list[str], w: float) -> None:
    room = w - 18
    if len(title) * 7.0 > room:
        warn(f"box {nid}: title may overflow its box ({len(title)} chars in {w:.0f}px)")
    for s in subs:
        if len(s) * 5.9 > room:
            warn(f"box {nid}: line may overflow its box: {s[:50]!r} ({len(s)} chars in {w:.0f}px)")


def node_g(nid: str, kind: str, x: float, y: float, w: float, h: float, title: str, subs: list[str]) -> str:
    fit_check(nid, title, subs, w)
    cx = x + w / 2
    block = 14 + (5 + 16 * len(subs) if subs else 0)
    nt_y = y + (h - block) / 2 + 12
    texts = f'<text class="nt" x="{cx:g}" y="{nt_y:.0f}" text-anchor="middle">{esc(title)}</text>'
    for i, s in enumerate(subs):
        texts += f'<text class="ns" x="{cx:g}" y="{nt_y + 19 + 16 * i:.0f}" text-anchor="middle">{esc(s)}</text>'
    return (f'<g class="n {kind}" data-id="{nid}" tabindex="0" role="button">'
            f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="8"/>{texts}</g>')


def subs_of(item: dict) -> list[str]:
    if "lines" in item:
        return list(item["lines"])
    return [item["sub"]] if item.get("sub") else []


def flow_view(v: dict) -> tuple[str, list[str], dict]:
    W = v.get("width", 680)
    x, w = v.get("x", 190), v.get("w", 300)
    y = v.get("top", 24)
    box_h, gap = v.get("box_h", 52), v.get("gap", 22)
    mid = f"arrow-{v['id']}"
    parts, rects, order = [], {}, []
    prev_bottom = None
    for it in v["items"]:
        h = it.get("h", box_h)
        if prev_bottom is not None:
            y = prev_bottom + it.get("gap_before", gap)
            cx = x + w / 2
            parts.append(f'<line class="wire" x1="{cx:g}" y1="{prev_bottom:g}" x2="{cx:g}" y2="{y - 2:g}" marker-end="url(#{mid})"/>')
            if it.get("label_before"):
                parts.append(f'<text class="lbl" x="{cx + 12:g}" y="{(prev_bottom + y) / 2 + 3:g}">{esc(it["label_before"])}</text>')
        rects[it["id"]] = (x, y, w, h)
        parts.append(node_g(it["id"], it["kind"], x, y, w, h, it["title"], subs_of(it)))
        order.append(it["id"])
        prev_bottom = y + h
    for s in v.get("side", []):
        a, b = s["span"]
        if a not in rects or b not in rects:
            err(f"view {v['id']}: side box {s['id']} spans unknown items {s['span']}")
            continue
        top, bottom = rects[a][1], rects[b][1] + rects[b][3]
        sx, sw = s.get("x", x + w + 34), s.get("w", 148)
        marks = []
        for m in s.get("marks", []):
            if m["to"] not in rects:
                err(f"view {v['id']}: mark points at unknown item {m['to']}")
                continue
            tx, ty, tw, th = rects[m["to"]]
            marks.append((ty + th / 2, m["text"], tx + tw))
        title = s["title"] if isinstance(s["title"], list) else [s["title"]]
        mid_y = (top + bottom) / 2
        cand = mid_y
        for step in range(0, 200, 10):
            ok = False
            for c in (mid_y - step, mid_y + step):
                if all(abs(c - cy) >= 36 + 9 * (len(title) - 1) for cy, _, _ in marks) and top + 30 <= c <= bottom - 30:
                    cand, ok = c, True
                    break
            if ok:
                break
        subs = []
        block = f'<g class="n {s["kind"]}" data-id="{s["id"]}" tabindex="0" role="button"><rect x="{sx:g}" y="{top:g}" width="{sw:g}" height="{bottom - top:g}" rx="8"/>'
        for i, t in enumerate(title):
            block += f'<text class="nt" x="{sx + sw / 2:g}" y="{cand + 18 * i:g}" text-anchor="middle">{esc(t)}</text>'
        for cy, text, right in marks:
            block += f'<text class="ns" x="{sx + sw / 2:g}" y="{cy + 4:g}" text-anchor="middle">{esc(text)}</text>'
        block += "</g>"
        parts.append(block)
        for cy, _, right in marks:
            parts.append(f'<path class="wire-d" d="M{sx:g} {cy:g} L{right + 2:g} {cy:g}" marker-end="url(#{mid})"/>')
        order.append(s["id"])
        fit_check(s["id"], max(title, key=len), [], sw)
    H = v.get("height", prev_bottom + 24)
    return svg_wrap(v, W, H, marker(mid), parts), order, rects


def straight(a, b, e) -> tuple[str, float, float]:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ox0, ox1 = max(ax, bx), min(ax + aw, bx + bw)
    oy0, oy1 = max(ay, by), min(ay + ah, by + bh)
    if by >= ay + ah - 1 and ox1 > ox0:
        x = (ox0 + ox1) / 2
        return f"M{x:g} {ay + ah:g} L{x:g} {by:g}", x + 10, (ay + ah + by) / 2 + 4
    if bx >= ax + aw - 1 and oy1 > oy0:
        y = (oy0 + oy1) / 2
        return f"M{ax + aw:g} {y:g} L{bx:g} {y:g}", ax + aw + 8, y - 6
    raise ValueError("no straight connector between these boxes; give the edge an explicit 'd' path")


def crossings(d: str, rects: dict, skip=()) -> list[str]:
    """Names of boxes whose interior an axis-aligned segment of path ``d`` (absolute M/L only) passes through."""
    nums = [float(t) for t in re.findall(r"-?\d+(?:\.\d+)?", d)]
    pts = list(zip(nums[0::2], nums[1::2]))
    hit = []
    # a new "M" starts a new subpath; split on it so segments are not joined across subpaths
    for sub in re.split(r"(?=M)", d):
        n = [float(t) for t in re.findall(r"-?\d+(?:\.\d+)?", sub)]
        p = list(zip(n[0::2], n[1::2]))
        for (x1, y1), (x2, y2) in zip(p, p[1:]):
            for rid, (rx, ry, rw, rh) in rects.items():
                if rid in skip:
                    continue
                if x1 == x2 and rx + 1 < x1 < rx + rw - 1 and min(y1, y2) < ry + rh - 1 and max(y1, y2) > ry + 1:
                    hit.append(rid)
                if y1 == y2 and ry + 1 < y1 < ry + rh - 1 and min(x1, x2) < rx + rw - 1 and max(x1, x2) > rx + 1:
                    hit.append(rid)
    return sorted(set(hit))


def manual_view(v: dict) -> tuple[str, list[str], dict]:
    W, H = v.get("width", 680), v["height"]
    mid = f"arrow-{v['id']}"
    parts, rects, order = [], {}, []
    for n in v["nodes"]:
        rects[n["id"]] = (n["x"], n["y"], n["w"], n["h"])
    for e in v.get("edges", []):
        cls = "wire-d" if e.get("dashed") else "wire"
        mk = "" if e.get("arrow") is False else f' marker-end="url(#{mid})"'
        lx, ly = e.get("lx"), e.get("ly")
        try:
            if "d" in e:
                d = e["d"]
            else:
                d, alx, aly = straight(rects[e["from"]], rects[e["to"]], e)
                lx, ly = (lx if lx is not None else alx), (ly if ly is not None else aly)
        except (KeyError, ValueError) as ex:
            err(f"view {v['id']}: bad edge {e}: {ex}")
            continue
        skip = {e.get("from"), e.get("to")} - {None}
        for rid in crossings(d, rects, skip):
            warn(f"view {v['id']}: edge {e.get('from') or d[:24]} -> {e.get('to') or ''} passes through box {rid}")
        parts.append(f'<path class="{cls}" d="{d}"{mk}/>')
        if e.get("label") and lx is not None:
            parts.append(f'<text class="lbl" x="{lx:g}" y="{ly:g}">{esc(e["label"])}</text>')
    for lab in v.get("labels", []):
        parts.append(f'<text class="lbl" x="{lab["x"]:g}" y="{lab["y"]:g}">{esc(lab["text"])}</text>')
    for n in v["nodes"]:
        parts.append(node_g(n["id"], n["kind"], n["x"], n["y"], n["w"], n["h"], n["title"], subs_of(n)))
        order.append(n["id"])
    return svg_wrap(v, W, H, marker(mid), parts), order, rects


def svg_wrap(v: dict, W, H, defs: str, parts: list[str]) -> str:
    vid = v["id"]
    if not v.get("title") or not v.get("desc"):
        warn(f"view {vid}: add 'title' and 'desc' for the SVG's accessible name")
    return (f'<svg viewBox="0 0 {W:g} {H:g}" role="img" aria-labelledby="t-{vid} d-{vid}">'
            f'<title id="t-{vid}">{esc(v.get("title", v["label"]))}</title>'
            f'<desc id="d-{vid}">{esc(v.get("desc", ""))}</desc>{defs}\n          ' + "\n          ".join(parts) + "\n        </svg>")


# ---------------------------------------------------------------- assemble

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("spec")
    ap.add_argument("out")
    ap.add_argument("--local", help="also write a full HTML page for local preview")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text())
    labels = {**LABELS, **(spec.get("labels") or {})}
    kind_labels = {**KIND_LABELS, **(spec.get("kind_labels") or {})}
    repos = resolve_repos(spec)
    snippets = build_snippets(spec, repos)
    releases = {k: Release(k, r) for k, r in (spec.get("releases") or {}).items()}

    nodes = spec["nodes"]
    for nid, d in nodes.items():
        if not ID_RE.match(nid) or nid.endswith("-code"):
            err(f"node id {nid!r}: use lowercase letters, digits, - or _, and do not end in '-code'")
        for k in ("kind", "title", "ref", "lede", "what"):
            if k not in d:
                err(f"node {nid}: missing {k!r}")
        if d.get("kind") not in KINDS:
            err(f"node {nid}: kind must be one of {KINDS}")
        d.setdefault("tag", kind_labels.get(d.get("kind"), ""))
        for sid in d.get("code", []):
            if sid not in snippets:
                err(f"node {nid}: code refers to unknown snippet {sid!r}")
        if d.get("widget") and d["widget"] not in (spec.get("widgets") or {}):
            err(f"node {nid}: unknown widget {d['widget']!r}")
        if d.get("evidence"):
            ev = d["evidence"]
            for k in ("lede", "recorded", "tables"):
                if k not in ev:
                    err(f"node {nid}: evidence needs {k!r}")
            for t in ev.get("tables", []):
                if not (isinstance(t, list) and len(t) == 2):
                    err(f"node {nid}: evidence.tables entries are [table, what it holds]")
            ev["examples"] = resolve_examples(nid, ev, releases)

    views_out, tabs, order, used_kinds, seen = [], [], {}, set(), set()
    for i, v in enumerate(spec["views"]):
        gen = flow_view if v["layout"] == "flow" else manual_view
        svg, ids, _ = gen(v)
        order[v["id"]] = v.get("order", ids)
        for nid in ids:
            if nid not in nodes:
                err(f"view {v['id']}: box {nid} has no entry in 'nodes'")
            if nid in seen:
                err(f"box id {nid} appears in more than one view")
            seen.add(nid)
        for it in (v.get("items") or v.get("nodes") or []) + v.get("side", []):
            used_kinds.add(it["kind"])
            if it["id"] in nodes and nodes[it["id"]].get("kind") != it["kind"]:
                warn(f"box {it['id']}: map kind {it['kind']} differs from its detail kind {nodes[it['id']].get('kind')}")
        v.setdefault("default_node", ids[0])
        views_out.append(f'      <div class="diagram" id="view-{v["id"]}" role="tabpanel" aria-labelledby="tab-{v["id"]}"'
                         f'{"" if i == 0 else " hidden"}>\n        {svg}\n      </div>')
        tabs.append(f'      <button id="tab-{v["id"]}" role="tab" aria-selected="{"true" if i == 0 else "false"}" '
                    f'aria-controls="view-{v["id"]}">{esc(v["label"])}</button>')
    for nid in nodes:
        if nid not in seen:
            warn(f"node {nid} has details but is not on any map")
    used = {s for d in nodes.values() for s in d.get("code", [])}
    for sid in snippets:
        if sid not in used:
            warn(f"snippet {sid} is not used by any box")

    for name, w in (spec.get("widgets") or {}).items():
        if w.get("type") == "waterfall":
            for k in ("min", "max", "threshold"):
                if k not in w:
                    err(f"widget {name}: waterfall needs {k!r}")
        elif w.get("type") == "checks":
            pass
        else:
            err(f"widget {name}: type must be 'waterfall' or 'checks'")

    legend = []
    for k in KINDS:
        if k in used_kinds:
            legend.append(f'      <span><i class="sw" style="background:var(--{k}-fill);border-color:var(--{k})"></i>{esc(kind_labels[k])}</span>')
    for x in spec.get("legend_extra", []):
        legend.append(f'      <span><svg width="22" height="10" aria-hidden="true"><line x1="0" y1="5" x2="22" y2="5" class="wire-d"/></svg>{esc(x["label"])}</span>')

    pins = ", ".join(f"{r['slug'].split('/')[-1]}@{r['sha'][:7]}" for r in repos.values())
    has_ev = any(d.get("evidence") for d in nodes.values())
    rel_note = ("" if not releases else " Rows on the " + labels["tab_evidence"] + " tab are copied from "
                + "; ".join(f"the {r.label} (run {r.run})" for r in releases.values() if r.ok)
                + ", and each file is checked against the release's own checksums.")
    hint = spec.get("hint") or (f"Select a box, or use Tab and Enter. Each box has an {labels['tab_note']} tab"
                                f"{', a ' + labels['tab_evidence'] + ' tab' if has_ev else ''} and a "
                                f"{labels['tab_code']} tab. Code is pinned to {pins}.{rel_note}")

    payload = {"nodes": {k: {**d, "code": d.get("code", [])} for k, d in nodes.items()},
               "snippets": snippets, "widgets": spec.get("widgets") or {}, "labels": labels, "order": order,
               "views": [{"id": v["id"], "label": v["label"], "default_node": v["default_node"]} for v in spec["views"]],
               "default_node": spec.get("default_node") or spec["views"][0]["default_node"]}
    if payload["default_node"] not in nodes:
        err(f"default_node {payload['default_node']!r} is not a node")

    tpl = (Path(__file__).resolve().parent.parent / "assets" / "template.html").read_text()
    page = (tpl.replace("{{TITLE}}", esc(spec["title"])).replace("{{EYEBROW}}", esc(spec["eyebrow"]))
            .replace("{{HEADING}}", esc(spec["heading"])).replace("{{INTRO}}", esc(spec["intro"]))
            .replace("{{VIEW_TABS}}", "\n".join(tabs)).replace("{{LEGEND}}", "\n".join(legend))
            .replace("{{VIEWS}}", "\n".join(views_out)).replace("{{HINT}}", esc(hint))
            .replace("{{SPEC_JSON}}", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")))

    for w in WARNINGS:
        print("warning:", w, file=sys.stderr)
    for e in ERRORS:
        print("ERROR:", e, file=sys.stderr)
    if ERRORS:
        print(f"{len(ERRORS)} error(s); nothing written", file=sys.stderr)
        return 1
    Path(args.out).write_text(page)
    if args.local:
        Path(args.local).write_text(
            '<!doctype html><html><head><meta charset=utf8><meta name=viewport content="width=device-width,'
            'initial-scale=1,viewport-fit=cover"><style>:root{color-scheme:light}body{margin:0;font:14px '
            '-apple-system,BlinkMacSystemFont,sans-serif;background:#faf9f5;color:#141413}</style></head><body>'
            + page + "</body></html>")
    print(f"wrote {args.out}: {len(nodes)} boxes, {len(snippets)} snippets, {len(spec['views'])} views, "
          f"{len(page) // 1024} KB, {len(WARNINGS)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
