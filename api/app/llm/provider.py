"""Swappable LLM provider factory.

Adding a provider later (openai, gemini, …) means one new branch here —
nothing else in the codebase imports a provider package directly.
"""

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import Settings, get_settings
from app.observability.llm_tracing import LlmTracingCallback

ROLES = ("classify", "draft", "chat")

# Wall-clock ceiling (seconds) for a single LLM HTTP request, applied at the
# httpx-client level so it bounds every request — including the AFC
# (automatic-function-calling) follow-up requests that with_structured_output
# triggers, which otherwise inherit the google-genai client's unbounded default
# and can hang for hours (see run 18).
LLM_TIMEOUT = 120

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

    cb = LlmTracingCallback(provider, model_name, role)

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
