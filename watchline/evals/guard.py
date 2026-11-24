"""A LangChain callback that records every model call's tokens and dollars and stops a run that spends too much.

Attach it to the agent through the run config (`{"callbacks": [guard]}`) and to the judge model (`model.with_config(callbacks=[guard])`).
It does four things:

- Records input, output, cache-read and cache-write tokens per call, per case and per run, with an estimated dollar cost.
- Aborts the whole run when the estimated cost reaches `max_usd` (sticky: every later call raises too).
- Aborts the current case when it makes more than `max_calls` model calls or runs past `timeout_s` (sticky until the next case).
- Writes build/agent-eval/usage-<run id>.json after every case, so a killed run still leaves a record.

LangChain only lets a callback stop a call by raising (`raise_error = True`). Some code between us and the model catches broad
exceptions (for example the retry in `ask`), so a raise alone could be swallowed. That is why the abort is sticky: every later call
raises again and spends nothing, and the test harness calls `check()` after each case to turn a swallowed abort into a failure.
"""
import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler

from watchline.evals.pricing import cost_usd, price_for

log = logging.getLogger("watchline.evals")

DEFAULT_MAX_USD = 0.25
DEFAULT_MAX_CALLS = 12
DEFAULT_TIMEOUT_S = 90.0
DEFAULT_JUDGE_MAX_CHARS = 12_000


class EvalAbort(Exception):
    """A spending or loop limit was hit. `run_wide` is true when no further case may start."""

    def __init__(self, message: str, run_wide: bool = False):
        super().__init__(message)
        self.run_wide = run_wide


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def truncate_records(text: str, max_chars: int) -> tuple[str, dict | None]:
    """The records text for a judge prompt, cut to `max_chars`. Returns (text, None) untouched or (cut text, what was cut)."""
    if len(text) <= max_chars:
        return text, None
    note = {"original_chars": len(text), "kept_chars": max_chars}
    return text[:max_chars] + f"\n[records truncated: {max_chars} of {len(text)} characters shown]", note


def _blank() -> dict:
    return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0, "cache_write_1h_tokens": 0,
            "usd": 0.0}


class EvalGuard(BaseCallbackHandler):
    raise_error = True      # a raise in a callback stops the model call only when the handler says so
    run_inline = True

    def __init__(self, model: str, *, max_usd: float = DEFAULT_MAX_USD, max_calls: int = DEFAULT_MAX_CALLS,
                 timeout_s: float = DEFAULT_TIMEOUT_S, out_dir: Path | None = None, run_id: str | None = None,
                 clock: Callable[[], float] = time.monotonic):
        price_for(model)      # refuse to start on a model with no recorded price
        self.model, self.max_usd, self.max_calls, self.timeout_s = model, max_usd, max_calls, timeout_s
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S")
        self.out_dir = out_dir
        self.clock = clock
        self.run = _blank()
        self.cases: list[dict] = []
        self.truncations: list[dict] = []
        self._case: dict | None = None
        self._case_id = ""
        self._deadline = 0.0
        self._case_abort = ""
        self._run_abort = ""

    @classmethod
    def from_env(cls, model: str, out_dir: Path | None = None) -> "EvalGuard":
        return cls(model, max_usd=env_float("EVAL_MAX_USD", DEFAULT_MAX_USD), max_calls=env_int("EVAL_MAX_CALLS", DEFAULT_MAX_CALLS),
                   timeout_s=env_float("EVAL_CASE_TIMEOUT_S", DEFAULT_TIMEOUT_S), out_dir=out_dir)

    # ---- cases ---------------------------------------------------------------------------------------------------------

    def start_case(self, case_id: str) -> None:
        if self._run_abort:
            raise EvalAbort(self._run_abort, run_wide=True)
        self._case_id, self._case_abort = case_id, ""
        self._case = _blank()
        self._case["truncations"] = []
        self._case["trace"] = []
        self._deadline = self.clock() + self.timeout_s

    def end_case(self) -> dict:
        """Close the current case and return its usage (also written to the usage file)."""
        usage = {"id": self._case_id, **(self._case or _blank()), "aborted": self._case_abort or self._run_abort or None}
        usage["usd"] = round(usage["usd"], 6)
        self.cases.append(usage)
        self._case = None
        self.write()
        return usage

    def check(self) -> None:
        """Raise if a limit was hit during the case, even if code between here and the model swallowed the first raise."""
        if self._run_abort:
            raise EvalAbort(self._run_abort, run_wide=True)
        if self._case_abort:
            raise EvalAbort(self._case_abort)

    # ---- callback hooks ------------------------------------------------------------------------------------------------

    def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        self._trace(messages)
        self._before_call()

    def _trace(self, messages) -> None:
        """Keep a short note of what each call was sent last (the newest message), so a loop can be read afterwards."""
        if self._case is None or not messages or not messages[0]:
            return
        last = messages[0][-1]
        content = last.content if isinstance(last.content, str) else json.dumps(last.content, default=str)
        entry = {"n": len(messages[0]), "last": getattr(last, "type", "?"), "name": getattr(last, "name", None), "text": content[:300]}
        # What the model said just before: its tool calls (name and arguments) and any text, to see why it called again.
        before = next((m for m in reversed(messages[0][:-1]) if getattr(m, "type", None) == "ai"), None)
        if before is not None:
            said = before.content if isinstance(before.content, str) else json.dumps(before.content, default=str)
            entry["model_said"] = {"text": said[:300], "tool_calls": [{"name": c["name"], "args": json.dumps(c["args"])[:200]}
                                                                    for c in getattr(before, "tool_calls", [])]}
        self._case["trace"].append(entry)

    def on_llm_start(self, serialized, prompts, **kwargs) -> None:
        self._before_call()

    def _before_call(self) -> None:
        if self._run_abort:
            raise EvalAbort(self._run_abort, run_wide=True)
        if self.run["usd"] >= self.max_usd:
            self._run_abort = f"estimated spend ${self.run['usd']:.4f} reached EVAL_MAX_USD ${self.max_usd:.2f}"
            raise EvalAbort(self._run_abort, run_wide=True)
        if self._case_abort:
            raise EvalAbort(self._case_abort)
        if self._case is not None:
            if self._case["calls"] >= self.max_calls:
                self._case_abort = f"case {self._case_id!r} reached the call limit of {self.max_calls} model calls"
                raise EvalAbort(self._case_abort)
            if self.clock() > self._deadline:
                self._case_abort = f"case {self._case_id!r} ran past the {self.timeout_s:.0f} s timeout"
                raise EvalAbort(self._case_abort)

    def on_llm_end(self, response, **kwargs) -> None:
        usage = _usage_of(response)
        usd = cost_usd(self.model, **usage)
        for bucket in (self.run, self._case):
            if bucket is None:
                continue
            bucket["calls"] += 1
            bucket["input_tokens"] += usage["input_tokens"]
            bucket["output_tokens"] += usage["output_tokens"]
            bucket["cache_read_tokens"] += usage["cache_read"]
            bucket["cache_write_tokens"] += usage["cache_write"]
            bucket["cache_write_1h_tokens"] += usage["cache_write_1h"]
            bucket["usd"] += usd
        if self.run["usd"] >= self.max_usd and not self._run_abort:
            self._run_abort = f"estimated spend ${self.run['usd']:.4f} reached EVAL_MAX_USD ${self.max_usd:.2f}"
            raise EvalAbort(self._run_abort, run_wide=True)

    # ---- judge input -----------------------------------------------------------------------------------------------------

    def note_truncation(self, item: str, note: dict) -> None:
        entry = {"case": self._case_id, "item": item[:80], **note}
        self.truncations.append(entry)
        if self._case is not None:
            self._case["truncations"].append(entry)
        log.warning("judge records truncated for %s: %s of %s chars kept", self._case_id or "(no case)", note["kept_chars"], note["original_chars"])

    # ---- reporting -----------------------------------------------------------------------------------------------------

    def report(self) -> dict:
        run = {**self.run, "usd": round(self.run["usd"], 6)}
        return {"model": self.model, "limits": {"max_usd": self.max_usd, "max_calls_per_case": self.max_calls, "timeout_s": self.timeout_s},
                "run": run, "cases": self.cases, "truncations": self.truncations, "aborted": self._run_abort or None,
                "price_source": "watchline/evals/pricing.py"}

    def write(self) -> Path | None:
        if self.out_dir is None:
            return None
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"usage-{self.run_id}.json"
        path.write_text(json.dumps(self.report(), indent=1))
        return path

    def summary(self) -> str:
        r = self.run
        lines = [f"Estimated cost ${r['usd']:.4f} ({self.model}; cap ${self.max_usd:.2f}): {r['calls']} calls, {r['input_tokens']} input "
                 f"({r['cache_read_tokens']} cache read, {r['cache_write_tokens'] + r['cache_write_1h_tokens']} cache write), {r['output_tokens']} output tokens."]
        lines += [f"  {c['id']}: ${c['usd']:.4f}, {c['calls']} calls" + (f"  ABORTED: {c['aborted']}" if c["aborted"] else "")
                  for c in self.cases]
        if self.truncations:
            lines.append(f"  judge records truncated {len(self.truncations)} time(s)")
        return "\n".join(lines)


def _usage_of(response) -> dict:
    """Token counts of one finished call. A call that reports none counts as zero calls' worth of tokens but still as a call."""
    total = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0, "cache_write_1h": 0}
    for gens in response.generations:
        for g in gens:
            u = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
            d = u.get("input_token_details") or {}
            total["input_tokens"] += u.get("input_tokens", 0)
            total["output_tokens"] += u.get("output_tokens", 0)
            total["cache_read"] += d.get("cache_read") or 0
            # langchain-anthropic reports writes under `cache_creation`, or, when the API gives the per-TTL breakdown, zeroes that
            # and uses these two keys instead (chat_models.py `_create_usage_metadata`); reading only the first showed 0 writes.
            total["cache_write"] += (d.get("cache_creation") or 0) + (d.get("ephemeral_5m_input_tokens") or 0)
            total["cache_write_1h"] += d.get("ephemeral_1h_input_tokens") or 0
    return total
