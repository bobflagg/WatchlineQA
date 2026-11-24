"""Per-token prices, in US dollars per million tokens (MTok).

Source: Anthropic pricing page, https://platform.claude.com/docs/en/about-claude/pricing ("Model pricing"), fetched 2026-11-24.
Check it against the Console before trusting a number (Stage 2 of docs/plans/eval-cost.md does this). Add a model here before using
it in an eval: an unknown model id makes the run refuse to start rather than guess a price.

Claude Haiku 5.5 is priced by prompt length: a request whose whole prompt (uncached input plus cache reads plus cache writes) is over
100,000 tokens pays the higher prices on every token of that request.
"""
from dataclasses import dataclass

LONG_PROMPT_TOKENS = 100_000


@dataclass(frozen=True)
class Price:
    input: float          # base input, per MTok
    cache_write: float    # 5 minute cache write (1.25x base input)
    cache_write_1h: float  # 1 hour cache write (2x base input)
    cache_read: float     # cache hit
    output: float


@dataclass(frozen=True)
class ModelPrice:
    standard: Price
    long_prompt: Price | None = None      # used when the prompt is over LONG_PROMPT_TOKENS

    def for_prompt(self, prompt_tokens: int) -> Price:
        return self.long_prompt if self.long_prompt and prompt_tokens > LONG_PROMPT_TOKENS else self.standard


PRICES: dict[str, ModelPrice] = {
    "claude-haiku-5-5": ModelPrice(standard=Price(0.10, 0.125, 0.20, 0.01, 0.50), long_prompt=Price(0.50, 0.625, 1.00, 0.05, 2.50)),
}


class UnknownModel(ValueError):
    pass


def price_for(model: str) -> ModelPrice:
    try:
        return PRICES[model]
    except KeyError:
        raise UnknownModel(f"No price recorded for model {model!r}; add it to watchline/evals/pricing.py (with its source) first.") from None


def cost_usd(model: str, *, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0,
             cache_write_1h: int = 0) -> float:
    """Dollar cost of one call. `input_tokens` is the whole prompt (what LangChain reports), cache reads and writes included.
    `cache_write` is the 5 minute (default) write, `cache_write_1h` the 1 hour one."""
    p = price_for(model).for_prompt(input_tokens)
    plain = max(input_tokens - cache_read - cache_write - cache_write_1h, 0)
    return (plain * p.input + cache_write * p.cache_write + cache_write_1h * p.cache_write_1h + cache_read * p.cache_read
            + output_tokens * p.output) / 1_000_000
