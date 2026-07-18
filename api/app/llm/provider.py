"""Swappable LLM provider factory.

Adding a provider later (openai, gemini, …) means one new branch here —
nothing else in the codebase imports a provider package directly.
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from app.config import Settings, get_settings
from app.observability.events import UsageEvent
from app.observability.sink import get_sink, current_run_id

ROLES = ("classify", "draft", "chat")

# Wall-clock ceiling (seconds) for a single LLM HTTP request, applied at the
# httpx-client level so it bounds every request — including the AFC
# (automatic-function-calling) follow-up requests that with_structured_output
# triggers, which otherwise inherit the google-genai client's unbounded default
# and can hang for hours (see run 18).
LLM_TIMEOUT = 120

class UsageCallback(BaseCallbackHandler):
    def __init__(self, provider: str, model: str, role: str):
        self.provider = provider
        self.model = model
        self.role = role
        # Feature B: keyed by LangChain's callback run_id UUID (concurrency-safe)
        self._start_times: dict = {}

    def on_llm_start(self, serialized, prompts, *, run_id=None, **kwargs) -> None:
        """Record start time keyed by LangChain's run_id for per-call latency."""
        if run_id is not None:
            from datetime import datetime, timezone
            self._start_times[str(run_id)] = datetime.now(timezone.utc)

    def on_llm_end(self, response: LLMResult, *, run_id=None, **kwargs) -> None:
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            input_tokens = 0
            output_tokens = 0

            if response.llm_output and "token_usage" in response.llm_output:
                usage = response.llm_output["token_usage"]
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)

            if response.generations and response.generations[0]:
                gen = response.generations[0][0]
                message = getattr(gen, "message", None)
                if message and hasattr(message, "usage_metadata") and message.usage_metadata:
                    usage = message.usage_metadata
                    input_tokens = usage.get("input_tokens", input_tokens)
                    output_tokens = usage.get("output_tokens", output_tokens)

            # Feature B: compute latency from stashed start time
            latency_ms: int | None = None
            if run_id is not None:
                key = str(run_id)
                start = self._start_times.pop(key, None)
                if start is not None:
                    latency_ms = int((now - start).total_seconds() * 1000)

            e = UsageEvent(
                provider=self.provider,
                model=self.model,
                role=self.role,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                run_id=current_run_id.get(),
                ts=now,
                latency_ms=latency_ms,
            )
            get_sink().record_usage(e)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Usage callback failed: {e}")


def extract_text(content) -> str:
    """Normalize LLM message content to plain text.

    Providers differ: some return a plain string, others (Gemini, Anthropic with
    thinking) return a list of content blocks.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


KNOWN_PROVIDERS = ("gemini", "anthropic", "groq")


def get_chat_model(role: str, settings: Settings | None = None) -> BaseChatModel:
    """Return the chat model configured for a role: classify | draft | chat.

    Model values may carry a per-role provider prefix, e.g.
    CLASSIFY_MODEL=groq/llama-3.1-8b-instant routes classification to Groq
    while other roles stay on MODEL_PROVIDER.
    """
    settings = settings or get_settings()
    if role not in ROLES:
        raise ValueError(f"Unknown role {role!r}; expected one of {ROLES}")
    model_name = getattr(settings, f"{role}_model")

    provider = settings.model_provider
    if "/" in model_name and model_name.split("/", 1)[0] in KNOWN_PROVIDERS:
        provider, model_name = model_name.split("/", 1)

    cb = UsageCallback(provider, model_name, role)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model_name, api_key=settings.anthropic_api_key, timeout=LLM_TIMEOUT, max_tokens=4096, max_retries=2, callbacks=[cb])

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        # client_args sets the underlying httpx client's default Timeout, which
        # — unlike the `timeout=` kwarg — bounds AFC follow-up calls too.
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=settings.gemini_api_key,
            timeout=LLM_TIMEOUT,
            max_retries=2,
            client_args={"timeout": float(LLM_TIMEOUT)},
            callbacks=[cb],
        )

    if provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(model=model_name, api_key=settings.groq_api_key, timeout=LLM_TIMEOUT, max_retries=2, callbacks=[cb])

    raise ValueError(
        f"Unknown model provider {provider!r} — wired up: 'gemini', 'anthropic', 'groq'; "
        "add a branch in app/llm/provider.py"
    )
