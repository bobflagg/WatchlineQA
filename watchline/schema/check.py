"""Compare what the code reads (`expected.py`) with the live graph: `make schema-check`.

Read-only and schema-level (procedures only, no data scans). A property counts as present when any node of the
label has it, so sparse data is not a schema break. Exit code 1 when anything is missing.
"""
import difflib
import os
import sys
from dataclasses import dataclass

from watchline.schema.expected import NODES, RELS


@dataclass(frozen=True)
class Actual:
    node_props: dict[str, set[str]]                        # label -> properties on any node of that label
    rel_props: dict[str, set[str]]                         # type -> properties on any relationship of that type
    rel_ends: dict[str, set[tuple[str, str]]]              # type -> (start label, end label) pairs


def _hint(name: str, options) -> str:
    close = difflib.get_close_matches(name, sorted(options), n=1, cutoff=0.6)
    return f" (did you mean {close[0]!r}?)" if close else ""


def compare(nodes=NODES, rels=RELS, actual: Actual | None = None) -> list[str]:
    """One plain sentence per problem; an empty list means the graph has everything the code reads."""
    assert actual is not None
    out: list[str] = []
    for label, props in sorted(nodes.items()):
        if label not in actual.node_props:
            out.append(f"label {label!r} is missing{_hint(label, actual.node_props)}")
            continue
        for p in sorted(props - actual.node_props[label]):
            out.append(f"label {label!r} has no property {p!r}{_hint(p, actual.node_props[label])}")
    for typ, ends in sorted(rels.items()):
        if typ not in actual.rel_ends:
            out.append(f"relationship type {typ!r} is missing{_hint(typ, actual.rel_ends)}")
            continue
        for start, end, props in ends:
            if (start, end) not in actual.rel_ends[typ]:
                out.append(f"relationship {typ!r} does not run from {start!r} to {end!r}; the graph has "
                           f"{sorted(actual.rel_ends[typ])}")
            for p in sorted(props - actual.rel_props.get(typ, set())):
                out.append(f"relationship {typ!r} has no property {p!r}{_hint(p, actual.rel_props.get(typ, set()))}")
    return out


def read_actual(driver, database: str) -> Actual:
    from neo4j import RoutingControl

    def run(q):
        return driver.execute_query(q, database_=database, routing_=RoutingControl.READ).records

    node_props: dict[str, set[str]] = {}
    for r in run("CALL db.schema.nodeTypeProperties() YIELD nodeLabels, propertyName RETURN nodeLabels, propertyName"):
        for label in r["nodeLabels"]:
            props = node_props.setdefault(label, set())
            if r["propertyName"]:
                props.add(r["propertyName"])
    rel_props: dict[str, set[str]] = {}
    for r in run("CALL db.schema.relTypeProperties() YIELD relType, propertyName RETURN relType, propertyName"):
        typ = r["relType"].strip(":`")
        props = rel_props.setdefault(typ, set())
        if r["propertyName"]:
            props.add(r["propertyName"])
    rel_ends: dict[str, set[tuple[str, str]]] = {t: set() for t in rel_props}
    for r in run("CALL db.schema.visualization() YIELD relationships UNWIND relationships AS r "
                 "RETURN type(r) AS t, labels(startNode(r)) AS a, labels(endNode(r)) AS b"):
        for a in r["a"]:
            for b in r["b"]:
                rel_ends.setdefault(r["t"], set()).add((a, b))
    return Actual(node_props, rel_props, rel_ends)


def main() -> int:
    from dotenv import load_dotenv
    from neo4j import GraphDatabase

    load_dotenv()
    missing = [k for k in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE") if not os.environ.get(k)]
    if missing:
        print(f"Set {', '.join(missing)} (see .env.example).")
        return 2
    try:
        driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
        try:
            problems = compare(actual=read_actual(driver, os.environ["NEO4J_DATABASE"]))
        finally:
            driver.close()
    except Exception as exc:     # down, wrong credentials or wrong database: say so, do not report a schema result
        print(f"Could not read the graph schema ({type(exc).__name__}: {exc}). Check that Neo4j is running and NEO4J_* are right.")
        return 2
    if problems:
        print(f"Schema check FAILED: {len(problems)} problem(s). The code reads these but the graph does not have them:")
        for p in problems:
            print(f"  - {p}")
        return 1
    n_props = sum(len(p) for p in NODES.values())
    n_rels = sum(len(v) for v in RELS.values())
    print(f"Schema OK: {len(NODES)} labels, {n_props} properties, {n_rels} relationships.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
