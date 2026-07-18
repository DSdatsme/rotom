"""Tests for llm/provider.py — role→model mapping and provider swap guardrails."""

import pytest

from app.config import Settings
from app.llm.provider import get_chat_model


def _settings(**overrides) -> Settings:
    defaults = dict(
        model_provider="anthropic",
        anthropic_api_key="test-key",
        classify_model="claude-haiku-4-5-20251001",
        draft_model="claude-sonnet-4-6",
        chat_model="claude-sonnet-4-6",
    )
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def test_roles_map_to_configured_models():
    s = _settings()
    assert get_chat_model("classify", s).model == "claude-haiku-4-5-20251001"
    assert get_chat_model("draft", s).model == "claude-sonnet-4-6"
    assert get_chat_model("chat", s).model == "claude-sonnet-4-6"


def test_unknown_role_raises():
    with pytest.raises(ValueError, match="role"):
        get_chat_model("nonsense", _settings())


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="provider"):
        get_chat_model("chat", _settings(model_provider="openai"))


def test_groq_provider_maps_roles():
    s = _settings(
        model_provider="groq",
        groq_api_key="test-key",
        classify_model="llama-3.3-70b-versatile",
    )
    assert get_chat_model("classify", s).model_name == "llama-3.3-70b-versatile"


def test_per_role_provider_prefix_overrides_global():
    """'provider/model' syntax routes one role to a different provider."""
    s = _settings(
        model_provider="gemini",
        gemini_api_key="g-key",
        groq_api_key="q-key",
        classify_model="groq/llama-3.1-8b-instant",
        chat_model="gemini-flash-latest",
    )
    assert get_chat_model("classify", s).model_name == "llama-3.1-8b-instant"  # ChatGroq
    assert get_chat_model("chat", s).model.endswith("gemini-flash-latest")  # ChatGoogleGenerativeAI


def test_gemini_provider_maps_roles():
    s = Settings(
        model_provider="gemini",
        gemini_api_key="test-key",
        classify_model="gemini-flash-latest",
        draft_model="gemini-2.5-pro",
        chat_model="gemini-2.5-pro",
        _env_file=None,
    )
    assert get_chat_model("classify", s).model.endswith("gemini-flash-latest")
    assert get_chat_model("draft", s).model.endswith("gemini-2.5-pro")
