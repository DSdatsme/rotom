"""LLM cost via genai-prices (bundled, offline price data — no network).

Price on the *resolved* model the provider reports (e.g. `gemini-3-flash-preview`);
aliases like `gemini-flash-latest` aren't in the price table and return None. Never raises.
Token semantics: `input_tokens` includes cached tokens (passed again as
`cache_read_tokens`, priced at the cache rate); Gemini's `output_tokens` already
include thinking tokens.
"""

import logging

from app.observability.semconv import PRICING_PROVIDERS

logger = logging.getLogger(__name__)


def cost_usd(
    provider: str,
    model: str | None,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
) -> float | None:
    if not model:
        return None
    ref = model.removeprefix("models/")
    try:
        from genai_prices import Usage, calc_price

        price = calc_price(
            Usage(
                input_tokens=input_tokens or 0,
                output_tokens=output_tokens or 0,
                cache_read_tokens=cache_read_tokens or None,
            ),
            model_ref=ref,
            provider_id=PRICING_PROVIDERS.get(provider, provider),
        )
        return float(price.total_price)
    except LookupError:
        return None
    except Exception:
        logger.debug("pricing failed for %s/%s", provider, model, exc_info=True)
        return None
