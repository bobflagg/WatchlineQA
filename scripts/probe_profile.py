"""Probe what `building_profile` hands the model for one address. No model calls: only Neo4j and the Geosupport sidecar.

    uv run python scripts/probe_profile.py                      # 5413 7 Avenue, Brooklyn
    uv run python scripts/probe_profile.py "224 54 Street, Brooklyn"

Prints the size of the result as the model receives it (the tool's dict as JSON), its top-level keys with their sizes, how many
entries each list or object holds, and the last 600 characters. The result holds no "facts": facts are written by the model into
its answer and point (as evidence) at sections of this result, so the entry counts below are what a fact can point at.
Tokens are estimated at 4 characters each; Haiku 5.5's tokenizer produces more, so treat it as a floor. Reads credentials from .env
through the app's own startup code and prints none of them.
"""
import json
import sys

from watchline.agent.chat import StartupError, connect
from watchline.agent.tools import make_building_profile_tool

DEFAULT_ADDRESS = "5413 7 Avenue, Brooklyn"
TAIL_CHARS = 600


def entries(value) -> str:
    if isinstance(value, list):
        return f"list of {len(value)}"
    if isinstance(value, dict):
        return f"object with {len(value)} keys"
    return type(value).__name__


def main(address: str) -> int:
    try:
        client, graph, pg, _rg, close = connect()
    except StartupError as exc:
        print(f"Cannot start: {exc}", file=sys.stderr)
        return 2
    try:
        result = make_building_profile_tool(client, graph, pg).invoke({"address": address})
    finally:
        close()

    text = json.dumps(result, default=str)
    print(f"address: {address!r}")
    print(f"status: {result.get('status')}   outcome: {(result.get('resolution') or {}).get('outcome')}")
    print(f"total: {len(text):,} characters, about {len(text) // 4:,} tokens (4 chars per token, a floor)\n")

    print(f"{'top-level key':<40}{'chars':>9}{'~tokens':>9}  entries")
    for key, value in sorted(result.items(), key=lambda kv: -len(json.dumps(kv[1], default=str))):
        size = len(json.dumps(value, default=str))
        print(f"{key:<40}{size:>9,}{size // 4:>9,}  {entries(value)}")

    lists = {k: v for k, v in result.items() if isinstance(v, list)}
    rows = sum(len(v) for v in lists.values())
    print(f"\nentries a fact can point at: {rows} rows across {len(lists)} list sections "
          f"({', '.join(f'{k}={len(v)}' for k, v in lists.items())})")
    buildings = result.get("buildings")
    if isinstance(buildings, list):
        print(f"buildings: {len(buildings)}; per building, the largest entry is "
              f"{max((len(json.dumps(b, default=str)) for b in buildings), default=0):,} chars")
    print("facts: none in the tool result; the model writes them, each with evidence pointing at a section above")

    print(f"\nlast {TAIL_CHARS} characters:\n{text[-TAIL_CHARS:]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS))
