"""LLM_PROVIDER: the Anthropic API locally, Amazon Bedrock (IAM, no API key) on AWS."""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import pytest

from wealth.agent.guard import ScopeGuard
from wealth.agent.loop import AdvisorAgent
from wealth.config import get_settings
from wealth.llm import make_client, missing_setup

A1 = 1


def _settings(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    return get_settings()


def test_default_is_anthropic_api(monkeypatch):
    s = _settings(monkeypatch, ANTHROPIC_API_KEY="sk-test")
    assert s.llm_provider == "anthropic"
    assert (s.anthropic_model, s.guard_model) == ("claude-sonnet-5-5", "claude-haiku-5-5")
    assert type(make_client(s)) is anthropic.Anthropic
    assert missing_setup(s) is None


def test_bedrock_uses_inference_profiles_and_no_key(monkeypatch):
    s = _settings(monkeypatch, LLM_PROVIDER="bedrock", BEDROCK_REGION="us-west-1", ANTHROPIC_API_KEY="")
    assert s.anthropic_model == "us.anthropic.claude-sonnet-5-5"
    assert s.guard_model == "us.anthropic.claude-haiku-5-5"
    client = make_client(s)
    assert isinstance(client, anthropic.AnthropicBedrock)
    assert client.aws_region == "us-west-1"
    assert missing_setup(s) is None  # no API key needed


def test_bedrock_region_falls_back_to_aws_region(monkeypatch):
    s = _settings(monkeypatch, LLM_PROVIDER="bedrock", AWS_REGION="us-west-1")
    assert s.bedrock_region == "us-west-1"


def test_model_overrides(monkeypatch):
    s = _settings(
        monkeypatch, LLM_PROVIDER="bedrock", ANTHROPIC_MODEL="us.anthropic.claude-haiku-5-5", GUARD_MODEL="g"
    )
    assert (s.anthropic_model, s.guard_model) == ("us.anthropic.claude-haiku-5-5", "g")


def test_missing_setup_messages(monkeypatch):
    s = _settings(monkeypatch, ANTHROPIC_API_KEY="")
    assert "ANTHROPIC_API_KEY" in missing_setup(s)
    s = _settings(
        monkeypatch, LLM_PROVIDER="bedrock", BEDROCK_REGION="", AWS_REGION="", AWS_DEFAULT_REGION=""
    )
    assert "BEDROCK_REGION" in missing_setup(s)
    with pytest.raises(RuntimeError):
        make_client(s)


def test_unknown_provider_refused(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="LLM_PROVIDER"):
        get_settings()


class _Recorder:
    """Captures the request; answers with plain text."""

    def __init__(self):
        self.requests = []
        msg = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="hi")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )
        create = lambda **kw: (self.requests.append(kw), msg)[1]  # noqa: E731
        self.messages = SimpleNamespace(create=create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))


def test_bedrock_requests_have_no_server_side_fallback(monkeypatch, conn):
    _settings(monkeypatch, LLM_PROVIDER="bedrock", BEDROCK_REGION="us-west-1")
    # Even a first-party model name never gets the Claude-API-only fallback beta on Bedrock.
    for model in ("us.anthropic.claude-sonnet-5-5", "claude-sonnet-5-5"):
        client = _Recorder()
        AdvisorAgent(A1, client, model=model, conn=conn).ask("hello")
        req = client.requests[0]
        assert "fallbacks" not in req and "betas" not in req
        assert req["model"] == model
        assert req["cache_control"] == {"type": "ephemeral"}  # prompt caching still on


def test_guard_uses_the_providers_small_model(monkeypatch):
    _settings(monkeypatch, LLM_PROVIDER="bedrock", BEDROCK_REGION="us-west-1")
    assert ScopeGuard(_Recorder()).model == "us.anthropic.claude-haiku-5-5"
    _settings(monkeypatch, LLM_PROVIDER="anthropic")
    assert ScopeGuard(_Recorder()).model == "claude-haiku-5-5"
