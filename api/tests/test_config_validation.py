"""Startup guard: a blank/placeholder API_TOKEN must fail fast, not silently
come up with fail-open auth (Bearer with an empty secret)."""

import pytest

from app.config import Settings, validate_required_settings


def test_blank_api_token_raises():
    with pytest.raises(ValueError, match="API_TOKEN"):
        validate_required_settings(Settings(api_token=""))


def test_placeholder_api_token_raises():
    with pytest.raises(ValueError, match="API_TOKEN"):
        validate_required_settings(Settings(api_token="change-me-long-random-string"))


def test_real_api_token_passes():
    # Should not raise.
    validate_required_settings(Settings(api_token="a-real-long-random-token"))
