"""``AttributeExtractor`` over OpenRouter's OpenAI-compatible chat completions API."""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import openai
from openai import AsyncOpenAI

from scrappy.application.ports.extractor import (
    ExtractionInput,
    ExtractionRejection,
    ExtractionResult,
)
from scrappy.domain.extraction import TokenUsage
from scrappy.infrastructure.extraction.prompt import (
    CORRECTION_TEMPLATE,
    PROMPT_VERSION,
    build_messages,
)
from scrappy.infrastructure.extraction.schema_builder import ExtractionSchema, InvalidAnswerError

log = logging.getLogger(__name__)

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429})
_MAX_ATTEMPTS = 2  # first answer + one corrective retry


class _ProviderError(Exception):
    def __init__(self, reason: str, *, retryable: bool) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


class OpenRouterAttributeExtractor:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 60.0,
        structured_output: bool = True,
        referer: str | None = None,
        app_title: str | None = None,
        temperature: float = 0.0,
        client: AsyncOpenAI | None = None,
    ) -> None:
        headers: dict[str, str] = {}
        if referer:
            headers["HTTP-Referer"] = referer
        if app_title:
            headers["X-Title"] = app_title
        self._client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,  # retries belong to the job queue (ADR 0006)
            default_headers=headers or None,
        )
        self._model = model
        self._structured = structured_output
        self._temperature = temperature

    async def extract(self, request: ExtractionInput) -> ExtractionResult | ExtractionRejection:
        schema = ExtractionSchema(request.categories)
        usage = TokenUsage()
        correction: list[dict[str, str]] = []
        last_error = "no answer"
        for _ in range(_MAX_ATTEMPTS):
            try:
                content, call_usage = await self._complete(request, schema, correction)
            except _ProviderError as error:
                return ExtractionRejection(
                    error.reason, retryable=error.retryable, model=self._model, usage=usage
                )
            usage += call_usage
            try:
                answer = schema.validate(_parse_json(content))
            except InvalidAnswerError as error:
                last_error = str(error)
                log.info("invalid LLM answer for %s: %s", request.offer_id, last_error)
                correction = [
                    {"role": "assistant", "content": content[:4000]},
                    {"role": "user", "content": CORRECTION_TEMPLATE.format(error=last_error)},
                ]
                continue
            return ExtractionResult(
                category=answer.category,
                attributes=answer.attributes,
                model=self._model,
                prompt_version=PROMPT_VERSION,
                usage=usage,
                notes=answer.notes,
            )
        return ExtractionRejection(
            f"invalid model output after retry: {last_error}",
            retryable=False,
            model=self._model,
            usage=usage,
        )

    async def _complete(
        self,
        request: ExtractionInput,
        schema: ExtractionSchema,
        correction: list[dict[str, str]],
    ) -> tuple[str, TokenUsage]:
        try:
            if self._structured:
                try:
                    return await self._call(request, schema, correction, structured=True)
                except openai.BadRequestError as error:
                    log.warning("structured output rejected (%s); using json_object", error)
                    self._structured = False
            return await self._call(request, schema, correction, structured=False)
        except openai.APITimeoutError as error:
            raise _ProviderError(f"LLM request timed out: {error}", retryable=True) from error
        except openai.APIConnectionError as error:
            raise _ProviderError(f"LLM connection error: {error}", retryable=True) from error
        except openai.APIStatusError as error:
            status = error.status_code
            retryable = status >= 500 or status in _RETRYABLE_STATUS
            raise _ProviderError(
                f"LLM provider returned HTTP {status}: {error.message}", retryable=retryable
            ) from error

    async def _call(
        self,
        request: ExtractionInput,
        schema: ExtractionSchema,
        correction: list[dict[str, str]],
        *,
        structured: bool,
    ) -> tuple[str, TokenUsage]:
        messages = build_messages(
            request, response_schema=None if structured else schema.json_schema
        )
        messages.extend(correction)
        response_format: Any = schema.response_format if structured else {"type": "json_object"}
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # pyright: ignore[reportArgumentType]
            response_format=response_format,
            temperature=self._temperature,
            extra_body={"usage": {"include": True}},  # OpenRouter: report cost
        )
        usage = _usage_of(response)
        if not response.choices:
            return "", usage
        return response.choices[0].message.content or "", usage


def _parse_json(content: str) -> object:
    text = content.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    if not text:
        raise InvalidAnswerError("the reply was empty; reply with a JSON object")
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise InvalidAnswerError(f"the reply is not valid JSON ({error.msg})") from error


def _usage_of(response: Any) -> TokenUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()
    extra = getattr(usage, "model_extra", None) or {}
    raw_cost = getattr(usage, "cost", None)
    if raw_cost is None:
        raw_cost = extra.get("cost")
    cost: Decimal | None = None
    if raw_cost is not None:
        try:
            cost = Decimal(str(raw_cost))
        except InvalidOperation:
            cost = None
    return TokenUsage(
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        cost_usd=cost,
    )
