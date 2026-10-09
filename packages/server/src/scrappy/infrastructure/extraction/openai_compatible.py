"""Sync ``AttributeExtractor`` for any OpenAI-compatible ``/v1/chat/completions`` server.

Works with Ollama (``http://localhost:11434/v1``), LM Studio (``http://localhost:1234/v1``),
vLLM, llama.cpp server, and hosted OpenAI-compatible APIs. ``openrouter.py`` is a thin preset
on top (ADR 0010 section 8).

Structured-output levels (``StructuredOutput``):

* ``json_schema``: strict ``response_format`` with our schema. A 400 from the provider
  downgrades the adapter to ``json_object`` for the rest of the process (logged once).
* ``json_object``: ``response_format: json_object``; the schema goes into the prompt.
* ``prompt_only``: no ``response_format`` at all; the schema goes into the prompt and our
  validation (``ExtractionSchema.validate`` + the domain) decides.

Error mapping to ``RejectionKind`` (see ``ports/extractor.py``): 402 -> QUOTA; 401/403/404
and connection errors -> UNAVAILABLE (the reconciler falls back to the next profile); timeout,
408/409/425/429 and 5xx -> TRANSIENT; other 4xx -> PERMANENT; invalid answers (after one
corrective retry) -> INVALID_OUTPUT.

Health check: ``GET {base_url}/models`` and verify the model id is listed (Ollama, LM Studio
and OpenRouter all serve it). With ``probe=True`` one tiny structured request checks the
structured-output level and downgrades it when rejected.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

import openai
from openai import AsyncOpenAI

from scrappy.application.ports.extraction_backends import ProfileHealth, StructuredOutput
from scrappy.application.ports.extractor import (
    ExtractionInput,
    ExtractionRejection,
    ExtractionResult,
    RejectionKind,
)
from scrappy.domain.category import AttributeSpec, AttributeType, Category, CategoryName
from scrappy.domain.extraction import TokenUsage
from scrappy.domain.offer import ContentHash, OfferId
from scrappy.domain.shared import SourceId
from scrappy.infrastructure.extraction.prompt import (
    CORRECTION_TEMPLATE,
    PROMPT_VERSION,
    build_messages,
)
from scrappy.infrastructure.extraction.schema_builder import ExtractionSchema, InvalidAnswerError

log = logging.getLogger(__name__)

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
_TRANSIENT_STATUS = frozenset({408, 409, 425, 429})
_UNAVAILABLE_STATUS = frozenset({401, 403, 404})
_MAX_ATTEMPTS = 2  # first answer + one corrective retry
NO_KEY = "not-needed"
"""Placeholder bearer token for servers without auth (the OpenAI client requires one)."""
MAX_LISTED = 8


class _ProviderError(Exception):
    def __init__(self, reason: str, *, kind: RejectionKind, retryable: bool) -> None:
        super().__init__(reason)
        self.reason = reason
        self.kind = kind
        self.retryable = retryable


class OpenAICompatibleExtractor:
    """Implements ``AttributeExtractor`` and ``ProfileHealthCheck``."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        structured_output: StructuredOutput = StructuredOutput.JSON_SCHEMA,
        timeout: float = 60.0,
        headers: Mapping[str, str] | None = None,
        temperature: float = 0.0,
        extra_body: Mapping[str, Any] | None = None,
        client: AsyncOpenAI | None = None,
        key_hint: str | None = None,
    ) -> None:
        self._client = client or AsyncOpenAI(
            api_key=api_key or NO_KEY,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,  # retries belong to the reconciler (backoff per offer)
            default_headers=dict(headers) if headers else None,
        )
        self._base_url = base_url
        self._model = model
        self.structured_output = structured_output
        """Effective level; may be downgraded at runtime or by a probe."""
        self._temperature = temperature
        self._extra_body: dict[str, Any] = dict(extra_body or {})
        self._key_hint = key_hint

    @property
    def model(self) -> str:
        return self._model

    # ------------------------------------------------------------------ extraction
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
                    error.reason,
                    retryable=error.retryable,
                    model=self._model,
                    usage=usage,
                    kind=error.kind,
                )
            usage += call_usage
            try:
                answer = schema.validate(parse_json(content))
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
            kind=RejectionKind.INVALID_OUTPUT,
        )

    async def _complete(
        self,
        request: ExtractionInput,
        schema: ExtractionSchema,
        correction: list[dict[str, str]],
    ) -> tuple[str, TokenUsage]:
        try:
            if self.structured_output is StructuredOutput.JSON_SCHEMA:
                try:
                    return await self._call(request, schema, correction, self.structured_output)
                except openai.BadRequestError as error:
                    log.warning("structured output rejected (%s); using json_object", error)
                    self.structured_output = StructuredOutput.JSON_OBJECT
            return await self._call(request, schema, correction, self.structured_output)
        except openai.APITimeoutError as error:
            raise _ProviderError(
                f"LLM request timed out: {error}", kind=RejectionKind.TRANSIENT, retryable=True
            ) from error
        except openai.APIConnectionError as error:
            raise _ProviderError(
                f"cannot reach {self._base_url}: {error}",
                kind=RejectionKind.UNAVAILABLE,
                retryable=True,
            ) from error
        except openai.APIStatusError as error:
            status = error.status_code
            kind = status_kind(status)
            raise _ProviderError(
                f"LLM provider returned HTTP {status}: {error.message}",
                kind=kind,
                retryable=kind in (RejectionKind.TRANSIENT, RejectionKind.QUOTA),
            ) from error

    async def _call(
        self,
        request: ExtractionInput,
        schema: ExtractionSchema,
        correction: list[dict[str, str]],
        level: StructuredOutput,
    ) -> tuple[str, TokenUsage]:
        strict = level is StructuredOutput.JSON_SCHEMA
        messages = build_messages(request, response_schema=None if strict else schema.json_schema)
        messages.extend(correction)
        response_format: Any = openai.NOT_GIVEN  # prompt_only: no response_format at all
        if level is StructuredOutput.JSON_SCHEMA:
            response_format = schema.response_format
        elif level is StructuredOutput.JSON_OBJECT:
            response_format = {"type": "json_object"}
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # pyright: ignore[reportArgumentType]
            temperature=self._temperature,
            response_format=response_format,
            extra_body=self._extra_body or None,
        )
        usage = usage_of(response)
        if not response.choices:
            return "", usage
        return response.choices[0].message.content or "", usage

    # ------------------------------------------------------------------ health
    async def check(self, *, probe: bool = False) -> ProfileHealth:
        try:
            page = await self._client.models.list()
            ids = [model.id async for model in page]
        except openai.AuthenticationError as error:
            hint = f" (set {self._key_hint})" if self._key_hint else ""
            return ProfileHealth(False, f"authentication failed at {self._base_url}{hint}: {error}")
        except openai.APIConnectionError as error:
            return ProfileHealth(
                False, f"cannot reach {self._base_url}: {error}. Is the server running?"
            )
        except openai.APIStatusError as error:
            return ProfileHealth(
                False, f"{self._base_url}/models answered HTTP {error.status_code}: {error.message}"
            )
        except Exception as error:
            return ProfileHealth(False, f"health check failed: {type(error).__name__}: {error}")
        if self._model not in ids:
            shown = ", ".join(sorted(ids)[:MAX_LISTED]) or "none"
            more = f" (+{len(ids) - MAX_LISTED} more)" if len(ids) > MAX_LISTED else ""
            return ProfileHealth(
                False,
                f"model {self._model!r} is not available at {self._base_url} "
                f"(available: {shown}{more}). Pull/load it (e.g. `ollama pull {self._model}`) "
                "or fix the profile's model.",
                model_available=False,
            )
        if not probe:
            return ProfileHealth(
                True,
                f"{self._base_url} lists {self._model}",
                model_available=True,
            )
        level = await self.probe()
        return ProfileHealth(
            True,
            f"{self._base_url} lists {self._model}; structured output: {level.value}",
            model_available=True,
            effective_structured_output=level,
        )

    async def probe(self) -> StructuredOutput:
        """Send one tiny request per level, from the configured one down, until one is
        accepted (HTTP 2xx and parsable JSON). Sets and returns the effective level."""
        request = _probe_input()
        schema = ExtractionSchema(request.categories)
        level: StructuredOutput | None = self.structured_output
        while level is not None:
            try:
                content, _ = await self._call(request, schema, [], level)
                parse_json(content)
            except (openai.BadRequestError, InvalidAnswerError) as error:
                log.warning("probe: %s not usable with %s (%s)", level.value, self._model, error)
                level = level.downgraded()
                continue
            except openai.APIError as error:
                log.warning("probe failed for %s: %s", self._model, error)
                return self.structured_output
            self.structured_output = level
            return level
        self.structured_output = StructuredOutput.PROMPT_ONLY
        return self.structured_output


def status_kind(status: int) -> RejectionKind:
    if status == 402:
        return RejectionKind.QUOTA
    if status in _UNAVAILABLE_STATUS:
        return RejectionKind.UNAVAILABLE
    if status >= 500 or status in _TRANSIENT_STATUS:
        return RejectionKind.TRANSIENT
    return RejectionKind.PERMANENT


def parse_json(content: str) -> object:
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


def usage_of(response: Any) -> TokenUsage:
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


def _probe_input() -> ExtractionInput:
    probe_category = Category(
        CategoryName("laptop"), 1, (AttributeSpec("ram_gb", AttributeType.INTEGER),)
    )
    return ExtractionInput(
        offer_id=OfferId(SourceId("probe"), "1"),
        content_hash=ContentHash("0" * 64),
        title="Laptop 16GB RAM",
        description="Laptop with 16 GB RAM.",
        description_truncated=False,
        params=(),
        price=None,
        categories=(probe_category,),
    )
