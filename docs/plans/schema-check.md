# Graph schema check (F01)

`make schema-check` (`python -m watchline.schema.check`) compares what the code reads with the live graph, so a rebuild
that drops or renames a name fails loudly instead of returning empty answers. No model calls.

- `watchline/schema/expected.py`: labels with the properties read, relationship types with endpoints and properties.
- `check.py`: `compare()` (pure) and `read_actual()` using `db.schema.nodeTypeProperties`, `relTypeProperties` and
  `visualization` (schema-level, no data scans). A property counts as present if any node has it. Messages carry a
  rename hint (difflib). Exit 0 ok, 1 problems, 2 cannot connect or env missing.
- `tests/test_schema_manifest.py` (in `make check`): regex scan of the Cypher strings; fails when a query uses a label,
  relationship type or `var.prop` not in `expected.py`. Limits: inline-map keys are not checked, a variable reused for
  several labels in one file is checked against their combined properties, `(n:A|B)` captures only A.
- `tests/test_schema_check.py`: unit tests of `compare()` plus one live test (skips when Neo4j is unreachable).

Verified on the current graph: 15 labels, 72 properties, 13 relationships all present. Maintenance: add any new name to
`expected.py` when a query starts reading it. Independent review found no coverage gaps; its connection-error finding was fixed.
