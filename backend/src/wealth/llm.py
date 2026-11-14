"""Which Claude endpoint the app talks to, chosen by LLM_PROVIDER.

- anthropic (default, local development): Anthropic's API, authenticated with ANTHROPIC_API_KEY.
- bedrock (AWS): Amazon Bedrock, authenticated with IAM. On ECS the task role's temporary credentials are
  picked up automatically, so no API key exists anywhere in the deployment.

The request code (agent loop, scope guard) is identical for both; only the client and the model IDs differ.
Bedrock model IDs are US cross-region inference profiles, e.g. us.anthropic.claude-sonnet-5-5: requests
are served from US regions only.
"""

from __future__ import annotations

from typing import Any

import anthropic

PROVIDERS = ("anthropic", "bedrock")

# (agent model, scope-guard model) per provider. ANTHROPIC_MODEL / GUARD_MODEL override them.
DEFAULT_MODELS = {
    "anthropic": ("claude-sonnet-5-5", "claude-haiku-5-5"),
    "bedrock": ("us.anthropic.claude-sonnet-5-5", "us.anthropic.claude-haiku-5-5"),
}


def make_client(settings: Any) -> Any:
    """An anthropic.Anthropic or anthropic.AnthropicBedrock; both expose the same messages API."""
    if settings.llm_provider == "bedrock":
        if not settings.bedrock_region:
            raise RuntimeError("LLM_PROVIDER=bedrock needs BEDROCK_REGION (or AWS_REGION).")
        # No keys passed: the AWS SDK credential chain finds them (ECS task role, or your local AWS profile).
        return anthropic.AnthropicBedrock(aws_region=settings.bedrock_region)
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def missing_setup(settings: Any) -> str | None:
    """What is missing before the assistant can call Claude, or None."""
    if settings.llm_provider == "anthropic" and not settings.anthropic_api_key:
        return "ANTHROPIC_API_KEY is not set (put it in .env), or use LLM_PROVIDER=bedrock."
    if settings.llm_provider == "bedrock" and not settings.bedrock_region:
        return "LLM_PROVIDER=bedrock needs BEDROCK_REGION (or AWS_REGION)."
    return None
