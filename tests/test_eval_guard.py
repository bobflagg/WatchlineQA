"""Cost recording and spend, call and time limits, tested with a scripted model: no API key, no network, no cost."""
import json
from itertools import count

import pytest
from langchain_core.messages import AIMessage
from langgraph.errors import GraphRecursionError
from test_agent import final, lookup, scripted
from test_agent_eval_q01 import judge
from test_agent_tools import FakeClient, FakeGraph, resolved
from test_profile import BUILDINGS, FakePG

from watchline.agent.agent import build_agent, memory_checkpointer
from watchline.agent.chat import RECURSION_LIMIT, ask
from watchline.agent.config import AGENT_KEY_ENV, EVAL_KEY_ENV, MissingKey, agent_model, eval_agent_model
from watchline.evals.guard import EvalAbort, EvalGuard, truncate_records
from watchline.evals.pricing import UnknownModel, cost_usd

MODEL = "claude-haiku-5-5"


def used(msg, inp=1000, out=100, read=0, write=0):
    """A scripted reply that reports token usage the way ChatAnthropic does (input includes cache reads and writes)."""
    msg.usage_metadata = {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out,
                          "input_token_details": {"cache_read": read, "cache_creation": write}}
    return msg


def loop_forever():
    """What a model that never produces a valid answer does: an invalid ModelAnswer call, again and again (the tool strategy
    sends the validation error back and the model tries again)."""
    for i in count():
        yield used(AIMessage(content="", tool_calls=[{"name": "ModelAnswer", "args": {"kind": "nonsense"}, "id": f"bad-{i}"}]))


def agent_for(responses):
    model, seen = scripted(responses)
    agent = build_agent(FakeClient(resolved()), FakeGraph(), FakePG(buildings=BUILDINGS), model=model, checkpointer=memory_checkpointer())
    return agent, seen


def cfg(guard, thread="t"):
    return {"configurable": {"thread_id": thread}, "callbacks": [guard]}


# ---- prices -----------------------------------------------------------------------------------------------------------

def test_cost_of_plain_input_and_output():
    assert cost_usd(MODEL, input_tokens=100_000, output_tokens=100_000) == pytest.approx(0.01 + 0.05)


def test_cost_splits_cache_reads_and_writes_from_plain_input():
    # 50k plain at $0.10, 10k written at $0.125, 40k read at $0.01 per MTok
    assert cost_usd(MODEL, input_tokens=100_000, output_tokens=0, cache_read=40_000, cache_write=10_000) == pytest.approx(
        0.005 + 0.00125 + 0.0004)


def test_a_prompt_over_100k_tokens_pays_the_higher_price_on_every_token_of_that_call():
    assert cost_usd(MODEL, input_tokens=200_000, output_tokens=1_000_000) == pytest.approx(200_000 * 0.50 / 1e6 + 2.50)
    assert cost_usd(MODEL, input_tokens=100_000, output_tokens=0) == pytest.approx(100_000 * 0.10 / 1e6)


def test_an_unrecorded_model_is_refused_not_guessed():
    with pytest.raises(UnknownModel):
        EvalGuard("claude-not-in-the-table")


# ---- recording --------------------------------------------------------------------------------------------------------

def test_every_call_is_recorded_per_case_and_per_run_and_written_after_each_case(tmp_path):
    guard = EvalGuard(MODEL, out_dir=tmp_path, run_id="r1")
    agent, _ = agent_for([used(lookup(), 2000, 50, read=1500, write=300), used(final("One lot."), 2500, 80, read=2000)])
    guard.start_case("c1")
    ask(agent, "tell me about 1 Main St, Manhattan", cfg(guard))
    usage = guard.end_case()
    assert (usage["calls"], usage["input_tokens"], usage["output_tokens"]) == (2, 4500, 130)
    assert (usage["cache_read_tokens"], usage["cache_write_tokens"]) == (3500, 300)
    expected = cost_usd(MODEL, input_tokens=2000, output_tokens=50, cache_read=1500, cache_write=300) + cost_usd(
        MODEL, input_tokens=2500, output_tokens=80, cache_read=2000)
    assert usage["usd"] == pytest.approx(expected, abs=1e-6)
    written = json.loads((tmp_path / "usage-r1.json").read_text())      # on disk before the run ends
    assert written["cases"][0]["id"] == "c1" and written["run"]["calls"] == 2
    assert "c1" in guard.summary() and "cache read" in guard.summary()


def test_a_judge_call_is_counted_in_the_run(tmp_path):
    guard = EvalGuard(MODEL, out_dir=tmp_path)
    judge_model, _ = scripted([used(AIMessage(content="PASS fine"), 3000, 10)])
    verdict = judge(judge_model.with_config(callbacks=[guard]), "item", "answer", [{"a": 1}], guard)
    assert verdict[0] is True and guard.run["calls"] == 1 and guard.run["input_tokens"] == 3000


# ---- the limits -------------------------------------------------------------------------------------------------------

def test_the_spend_cap_aborts_the_run_and_nothing_more_is_sent():
    guard = EvalGuard(MODEL, max_usd=0.0005)
    agent, seen = agent_for([used(lookup(), 6000, 100), used(final("x"), 6000, 100)])       # $0.00065 after the first call
    guard.start_case("c1")
    with pytest.raises(EvalAbort) as stop:
        ask(agent, "tell me about 1 Main St, Manhattan", cfg(guard))
    assert stop.value.run_wide and "EVAL_MAX_USD" in str(stop.value)
    assert len(seen["calls"]) == 1
    guard.end_case()
    with pytest.raises(EvalAbort):
        guard.start_case("c2")             # no later case may start


def test_a_looping_model_is_stopped_by_the_call_limit_and_the_next_case_can_run(tmp_path):
    guard = EvalGuard(MODEL, max_calls=4, out_dir=tmp_path)
    agent, seen = agent_for(loop_forever())
    guard.start_case("loop")
    with pytest.raises(EvalAbort) as stop:
        ask(agent, "hi", cfg(guard))
    assert not stop.value.run_wide and "call limit" in str(stop.value)
    assert len(seen["calls"]) == 4 and guard.run["calls"] == 4
    assert guard.end_case()["aborted"]
    agent2, _ = agent_for([used(final("fine"))])
    guard.start_case("next")
    assert ask(agent2, "hi", cfg(guard, "t2")).answer == "fine"
    guard.check()


def test_a_case_that_runs_past_the_timeout_is_stopped_before_its_next_call():
    now = [0.0]
    guard = EvalGuard(MODEL, timeout_s=90, clock=lambda: now[0])
    agent, seen = agent_for([used(lookup()), used(final("late"))])
    guard.start_case("slow")
    now[0] = 91.0
    with pytest.raises(EvalAbort, match="timeout"):
        ask(agent, "tell me about 1 Main St, Manhattan", cfg(guard))
    assert seen["calls"] == []


def test_a_limit_swallowed_by_the_correction_retry_still_fails_the_case():
    guard = EvalGuard(MODEL, max_calls=2)
    agent, _ = agent_for([used(lookup()), used(final("There are 77 complaints."))])     # the correction call would be the third
    guard.start_case("c")
    turn = ask(agent, "tell me about 1 Main St, Manhattan", cfg(guard))       # ask() keeps the first answer when the retry fails
    assert turn.unverified == ["77"]
    with pytest.raises(EvalAbort, match="call limit"):
        guard.check()


def test_without_a_guard_a_looping_model_still_stops_at_the_step_limit():
    agent, seen = agent_for(loop_forever())
    with pytest.raises(GraphRecursionError):
        ask(agent, "hi", {"configurable": {"thread_id": "t"}})
    assert 2 <= len(seen["calls"]) <= RECURSION_LIMIT


def test_a_caller_can_set_a_tighter_step_limit():
    agent, seen = agent_for(loop_forever())
    with pytest.raises(GraphRecursionError):
        ask(agent, "hi", {"configurable": {"thread_id": "t"}, "recursion_limit": 6})
    assert len(seen["calls"]) <= 6


# ---- the judge's records ----------------------------------------------------------------------------------------------

def test_truncate_records_cuts_and_says_so():
    assert truncate_records("short", 10) == ("short", None)
    text, note = truncate_records("x" * 30, 10)
    assert text.startswith("x" * 10) and "truncated" in text and note == {"original_chars": 30, "kept_chars": 10}


def test_the_judge_sees_a_truncated_record_and_the_cut_is_logged(monkeypatch, caplog):
    monkeypatch.setenv("EVAL_JUDGE_MAX_CHARS", "50")
    guard = EvalGuard(MODEL)
    guard.start_case("big")
    judge_model, seen = scripted([used(AIMessage(content="FAIL cut off"), 100, 5)])
    with caplog.at_level("WARNING", logger="watchline.evals"):
        judge(judge_model, "the item", "the answer", [{"k": "v" * 500}], guard)
    prompt = str(seen["calls"][0][0].content)
    assert "records truncated: 50 of" in prompt and len(prompt) < 1500
    assert guard.truncations[0]["case"] == "big" and guard.truncations[0]["kept_chars"] == 50
    assert "truncated" in caplog.text and guard.end_case()["truncations"]


def test_the_judge_default_limit_is_12000_characters(monkeypatch):
    monkeypatch.delenv("EVAL_JUDGE_MAX_CHARS", raising=False)
    guard = EvalGuard(MODEL)
    judge_model, seen = scripted([used(AIMessage(content="PASS ok"))])
    judge(judge_model, "i", "a", [{"k": "v" * 20_000}], guard)
    assert "records truncated: 12000 of" in str(seen["calls"][0][0].content)


# ---- keys -------------------------------------------------------------------------------------------------------------

def test_the_eval_model_needs_the_eval_key_and_ignores_the_generic_one(monkeypatch):
    monkeypatch.delenv(EVAL_KEY_ENV, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "generic-key")
    monkeypatch.setenv(AGENT_KEY_ENV, "agent-key")
    with pytest.raises(MissingKey, match=EVAL_KEY_ENV):
        eval_agent_model()
    monkeypatch.setenv(EVAL_KEY_ENV, "eval-key")
    assert eval_agent_model().anthropic_api_key.get_secret_value() == "eval-key"


def test_the_product_agent_uses_its_own_key_and_the_message_never_holds_a_key_value(monkeypatch):
    monkeypatch.delenv(AGENT_KEY_ENV, raising=False)
    monkeypatch.setenv(EVAL_KEY_ENV, "eval-key")
    with pytest.raises(MissingKey) as err:
        agent_model()
    assert AGENT_KEY_ENV in str(err.value) and "eval-key" not in str(err.value)
    monkeypatch.setenv(AGENT_KEY_ENV, "agent-key")
    assert agent_model().anthropic_api_key.get_secret_value() == "agent-key"


def test_the_trace_keeps_what_the_model_said_before_each_call(tmp_path):
    guard = EvalGuard(MODEL, out_dir=tmp_path)
    agent, _ = agent_for([used(lookup()), used(final("One lot."))])
    guard.start_case("c")
    ask(agent, "tell me about 1 Main St, Manhattan", cfg(guard))
    trace = guard.end_case() and guard.cases[0]["trace"]
    assert trace[0]["last"] == "human" and "model_said" not in trace[0]
    assert trace[1]["last"] == "tool" and trace[1]["name"] == "building_profile"
    assert trace[1]["model_said"]["tool_calls"][0]["name"] == "building_profile"
    assert "1 Main St" in trace[1]["model_said"]["tool_calls"][0]["args"]


# ---- the repeat guard -------------------------------------------------------------------------------------------------

def lookup_n(n):
    """The same lookup with its own call id, as a real model sends it (the shared `lookup()` helper reuses one id)."""
    return AIMessage(content="", tool_calls=[{"name": "building_profile", "args": {"address": "1 Main St", "borough": "Manhattan"},
                                              "id": f"call-{n}"}])


def test_a_repeated_identical_lookup_is_answered_with_a_nudge_not_run_again(tmp_path):
    guard = EvalGuard(MODEL, max_calls=8, out_dir=tmp_path)
    agent, seen = agent_for([used(lookup_n(1)), used(lookup_n(2)), used(lookup_n(3)), used(final("One lot."))])
    guard.start_case("repeat")
    turn = ask(agent, "tell me about 1 Main St, Manhattan", cfg(guard))
    guard.end_case()
    assert turn.answer.startswith("One lot.") and guard.cases[0]["calls"] == 4
    tool_msgs = [m for m in seen["calls"][-1] if m.type == "tool"]
    assert len(tool_msgs) == 3 and "bbl" in str(tool_msgs[0].content)                       # the first call ran
    assert all("repeat_lookup" in str(m.content) for m in tool_msgs[1:])     # the repeats did not run
    assert len(turn.tool_results) == 3 and turn.tool_results[0]["status"] == "ok"


def test_the_nudge_is_per_turn_and_per_arguments():
    other = AIMessage(content="", tool_calls=[{"name": "building_profile", "args": {"address": "2 Main St", "borough": "Manhattan"},
                                               "id": "call-2"}])
    agent, seen = agent_for([used(lookup_n(1)), used(other), used(final("two lots"))])
    turn = ask(agent, "tell me about 1 Main St and 2 Main St, Manhattan", cfg(EvalGuard(MODEL)))
    assert [t.get("status") for t in turn.tool_results] == ["ok", "ok"]                    # different arguments both run
    agent, seen = agent_for([used(lookup_n(1)), used(final("first")), used(lookup_n(2)), used(final("second"))])
    c = {"configurable": {"thread_id": "same"}}
    ask(agent, "tell me about 1 Main St, Manhattan", c)
    again = ask(agent, "and tell me again", c)
    assert again.tool_results[0]["status"] == "ok"                                          # a new turn may look up again


def test_the_guard_stops_the_live_loop_shape_before_the_call_limit():
    """The loop seen live: the identical call forever. With the nudge and a model that obeys it, the turn ends; with one that does
    not, the call limit still stops it."""
    stubborn = (used(AIMessage(content="", tool_calls=[{"name": "building_profile", "args": {"address": "1 Main St", "borough": "Manhattan"},
                                                        "id": f"c{i}"}])) for i in count())
    guard = EvalGuard(MODEL, max_calls=6)
    agent, seen = agent_for(stubborn)
    guard.start_case("stubborn")
    with pytest.raises(EvalAbort, match="call limit"):
        ask(agent, "tell me about 1 Main St, Manhattan", cfg(guard))
    tool_msgs = [m for m in seen["calls"][-1] if m.type == "tool"]
    assert "bbl" in str(tool_msgs[0].content) and all("repeat_lookup" in str(m.content) for m in tool_msgs[1:])


# ---- cache writes -----------------------------------------------------------------------------------------------------

def anthropic_usage(**kw):
    """The usage metadata langchain-anthropic builds from a real Anthropic `Usage`, as a scripted reply carries it."""
    from anthropic.types import Usage
    from langchain_anthropic.chat_models import _create_usage_metadata
    return _create_usage_metadata(Usage(**kw))


def reply_with(usage):
    msg = AIMessage(content="PASS ok")
    msg.usage_metadata = usage
    return msg


def recorded(usage, model_id=MODEL):
    guard = EvalGuard(model_id)
    judge_model, _ = scripted([reply_with(usage)])
    guard.start_case("w")
    judge(judge_model.with_config(callbacks=[guard]), "i", "a", [], guard)
    return guard.end_case()


def test_cache_writes_reported_per_ttl_are_logged_and_priced_at_1_25x():
    # What the API sends when it gives the TTL breakdown: langchain zeroes `cache_creation` and uses the ephemeral keys.
    usage = anthropic_usage(input_tokens=500, output_tokens=100, cache_read_input_tokens=2000, cache_creation_input_tokens=3000,
                            cache_creation={"ephemeral_5m_input_tokens": 3000, "ephemeral_1h_input_tokens": 0})
    assert usage["input_token_details"]["cache_creation"] == 0 and usage["input_token_details"]["ephemeral_5m_input_tokens"] == 3000
    got = recorded(usage)
    assert (got["input_tokens"], got["cache_read_tokens"], got["cache_write_tokens"], got["cache_write_1h_tokens"]) == (5500, 2000, 3000, 0)
    # 500 plain at $0.10, 3000 written at $0.125 (1.25x), 2000 read at $0.01, 100 output at $0.50, per MTok
    assert got["usd"] == pytest.approx((500 * 0.10 + 3000 * 0.125 + 2000 * 0.01 + 100 * 0.50) / 1e6, abs=1e-7)
    unpriced = (500 * 0.10 + 3000 * 0.10 + 2000 * 0.01 + 100 * 0.50) / 1e6          # what reading 0 writes used to give
    assert got["usd"] > unpriced


def test_a_usage_with_only_the_generic_cache_creation_field_is_logged_too():
    usage = anthropic_usage(input_tokens=500, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=1000)
    got = recorded(usage)
    assert got["cache_write_tokens"] == 1000 and got["input_tokens"] == 1500
    assert got["usd"] == pytest.approx((500 * 0.10 + 1000 * 0.125) / 1e6, abs=1e-7)


def test_one_hour_cache_writes_are_priced_at_2x():
    usage = anthropic_usage(input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=1000,
                            cache_creation={"ephemeral_5m_input_tokens": 400, "ephemeral_1h_input_tokens": 600})
    got = recorded(usage)
    assert (got["cache_write_tokens"], got["cache_write_1h_tokens"]) == (400, 600)
    assert got["usd"] == pytest.approx((400 * 0.125 + 600 * 0.20) / 1e6, abs=1e-7)


def test_write_prices_are_1_25x_and_2x_the_input_price_for_both_prompt_sizes():
    from watchline.evals.pricing import PRICES
    for p in (PRICES[MODEL].standard, PRICES[MODEL].long_prompt):
        assert p.cache_write == pytest.approx(1.25 * p.input) and p.cache_write_1h == pytest.approx(2 * p.input)
        assert p.cache_read == pytest.approx(0.1 * p.input)


def test_hedge_excuses_not_confirmation_that_but_not_a_bare_not_confirmed():
    from test_agent_eval_q01 import HEDGE
    assert HEDGE.search("a lead, not confirmation that they are the same party")
    assert not HEDGE.search("The grantee is the registered owner; this has not been confirmed elsewhere.")
