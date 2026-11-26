"""Drift guard: every label, relationship type and `var.prop` in the Cypher under watchline/ is in the manifest.

A regex scan, so it has limits: property keys in inline maps ({bbl: $x}) are not checked, a variable reused for
several labels in one file is checked against their combined properties, and `(n:A|B)` captures only A. `make schema-check`
against the live graph is the backstop."""
import ast
import re
from pathlib import Path

from watchline.schema.expected import NODES, RELS

ROOT = Path(__file__).resolve().parent.parent / "watchline"
NODE_RE = re.compile(r"\((\w*):([A-Z]\w*)")          # (var:Label  (no space after the colon, so annotations are skipped)
REL_RE = re.compile(r"\[(\w*):([A-Z_][A-Z_|]*)")     # [var:TYPE|TYPE
PROP_RE = re.compile(r"\b([a-z]\w*)\.([a-zA-Z]\w*)\b")


def _cypher_strings(path: Path) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and (NODE_RE.search(node.value) or REL_RE.search(node.value)):
            out.append(node.value)
    return out


def _scan():
    for path in sorted(ROOT.rglob("*.py")):
        if "schema" in path.parts:
            continue
        texts = _cypher_strings(path)
        if not texts:
            continue
        nodes, rels, bound, rel_bound = set(), set(), {}, {}
        for t in texts:
            for var, label in NODE_RE.findall(t):
                nodes.add(label)
                if var:
                    bound.setdefault(var, set()).add(label)
            for var, types in REL_RE.findall(t):
                for typ in types.split("|"):
                    rels.add(typ)
                    if var:
                        rel_bound.setdefault(var, set()).add(typ)
        props = set()
        for t in texts:
            for var, prop in PROP_RE.findall(t):
                if var in bound or var in rel_bound:      # a variable can name a node in one query and a relationship in another
                    props.add((var, prop, frozenset(bound.get(var, ())), frozenset(rel_bound.get(var, ()))))
        yield path.relative_to(ROOT), nodes, rels, props


def test_queries_use_only_listed_names():
    seen = 0
    problems = []
    for path, nodes, rels, props in _scan():
        seen += 1
        problems += [f"{path}: label {n!r} not in expected.py" for n in sorted(nodes - set(NODES))]
        problems += [f"{path}: relationship {r!r} not in expected.py" for r in sorted(rels - set(RELS))]
        for var, prop, labels, types in sorted(props, key=str):
            known = set().union(*(NODES.get(label, set()) for label in labels), *(p for t in types for _, _, p in RELS.get(t, [])))
            if prop not in known:
                problems.append(f"{path}: {var}.{prop} ({'/'.join(sorted(labels | types))}) not in expected.py")
    assert seen >= 8, "the scan found too few query files; the guard is not looking at the code"
    assert problems == []
