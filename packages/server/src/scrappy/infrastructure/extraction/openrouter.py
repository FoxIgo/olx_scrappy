"""OpenRouter preset of the generic OpenAI-compatible adapter (ADR 0010 section 8).

Adds what is specific to OpenRouter: its base URL, the optional attribution headers
(``HTTP-Referer``, ``X-Title``) and ``usage: {include: true}`` so the response reports the
cost. The batch backend (``BatchExtractionBackend``) for OpenRouter is a separate adapter.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openai import AsyncOpenAI

from scrappy.application.ports.extraction_backends import StructuredOutput
from scrappy.infrastructure.extraction.openai_compatible import (
    OpenAICompatibleExtractor,
    parse_json,
    usage_of,
)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"

__all__ = [
    "OPENROUTER_BASE_URL",
    "OpenRouterAttributeExtractor",
    "openrouter_headers",
    "parse_json",
    "usage_of",
]


def openrouter_headers(referer: str | None, app_title: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if referer:
        headers["HTTP-Referer"] = referer
    if app_title:
        headers["X-Title"] = app_title
    return headers


class OpenRouterAttributeExtractor(OpenAICompatibleExtractor):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = OPENROUTER_BASE_URL,
        timeout: float = 60.0,
        structured_output: bool | StructuredOutput = True,
        referer: str | None = None,
        app_title: str | None = None,
        temperature: float = 0.0,
        headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, Any] | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if isinstance(structured_output, bool):
            level = (
                StructuredOutput.JSON_SCHEMA if structured_output else StructuredOutput.JSON_OBJECT
            )
        else:
            level = structured_output
        body: dict[str, Any] = {"usage": {"include": True}}  # OpenRouter: report the cost
        body.update(extra_body or {})
        super().__init__(
            base_url=base_url,
            model=model,
            api_key=api_key,
            structured_output=level,
            timeout=timeout,
            headers={**openrouter_headers(referer, app_title), **(headers or {})},
            temperature=temperature,
            extra_body=body,
            client=client,
            key_hint=OPENROUTER_KEY_ENV,
        )
