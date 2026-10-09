from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from scrappy.application.ports.extraction_backends import StructuredOutput
from scrappy.application.ports.extractor import (
    ExtractionRejection,
    ExtractionResult,
    RejectionKind,
)
from scrappy.infrastructure.extraction.openai_compatible import NO_KEY, OpenAICompatibleExtractor

from .conftest import make_input
from .test_openrouter import LAPTOP_JSON, completion

BASE_URL = "http://lm.test/v1"
MODEL = "google/gemma-4-12b-qat"


class Server:
    """Records every request; replies are consumed in order (exceptions are raised)."""

    def __init__(self, *replies: httpx.Response | Exception) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def body(self, index: int = 0) -> dict[str, Any]:
        return json.loads(self.requests[index].content)


def build(
    server: Server,
    *,
    structured_output: StructuredOutput = StructuredOutput.JSON_SCHEMA,
    api_key: str | None = None,
    **kwargs: Any,
) -> OpenAICompatibleExtractor:
    client = AsyncOpenAI(
        api_key=api_key or NO_KEY,
        base_url=BASE_URL,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(server)),  # pyright: ignore[reportArgumentType]
        max_retries=0,
    )
    return OpenAICompatibleExtractor(
        base_url=BASE_URL,
        model=MODEL,
        api_key=api_key,
        structured_output=structured_output,
        client=client,
        **kwargs,
    )


def models(*ids: str) -> httpx.Response:
    data = [{"id": i, "object": "model", "created": 1, "owned_by": "x"} for i in ids]
    return httpx.Response(200, json={"object": "list", "data": data})


def bad_request() -> httpx.Response:
    return httpx.Response(400, json={"error": {"message": "response_format unsupported"}})


# ---------------------------------------------------------------- request body
async def test_request_has_model_temperature_and_merged_extra_body() -> None:
    server = Server(completion(LAPTOP_JSON))
    extractor = build(server, temperature=0.3, extra_body={"reasoning_effort": "none"})
    result = await extractor.extract(make_input())
    assert isinstance(result, ExtractionResult)
    assert result.model == MODEL
    body = server.body()
    assert body["model"] == MODEL
    assert body["temperature"] == 0.3
    assert body["reasoning_effort"] == "none"  # extra_body is merged at the top level
    assert str(server.requests[0].url) == f"{BASE_URL}/chat/completions"


async def test_json_schema_level_sends_strict_response_format() -> None:
    server = Server(completion(LAPTOP_JSON))
    await build(server).extract(make_input())
    response_format = server.body()["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True


async def test_json_object_level_puts_the_schema_in_the_prompt() -> None:
    server = Server(completion(LAPTOP_JSON))
    await build(server, structured_output=StructuredOutput.JSON_OBJECT).extract(make_input())
    body = server.body()
    assert body["response_format"] == {"type": "json_object"}
    assert "properties" in json.dumps(body["messages"])


async def test_prompt_only_level_has_no_response_format_but_the_schema_in_the_prompt() -> None:
    server = Server(completion(LAPTOP_JSON))
    result = await build(server, structured_output=StructuredOutput.PROMPT_ONLY).extract(
        make_input()
    )
    assert isinstance(result, ExtractionResult)
    body = server.body()
    assert "response_format" not in body
    assert "properties" in json.dumps(body["messages"])


async def test_strict_level_keeps_the_schema_out_of_the_prompt() -> None:
    server = Server(completion(LAPTOP_JSON))
    await build(server).extract(make_input())
    assert "properties" not in json.dumps(server.body()["messages"])


async def test_authorization_header_is_only_a_placeholder_without_a_key() -> None:
    server = Server(completion(LAPTOP_JSON))
    await build(server).extract(make_input())
    assert server.requests[0].headers["authorization"] == f"Bearer {NO_KEY}"


async def test_real_key_is_sent_as_bearer() -> None:
    server = Server(completion(LAPTOP_JSON))
    await build(server, api_key="sk-secret").extract(make_input())
    assert server.requests[0].headers["authorization"] == "Bearer sk-secret"


def test_default_client_has_no_retries_and_a_placeholder_key() -> None:
    extractor = OpenAICompatibleExtractor(base_url=BASE_URL, model=MODEL)
    client = extractor._client  # pyright: ignore[reportPrivateUsage]
    assert client.max_retries == 0
    assert client.api_key == NO_KEY
    assert str(client.base_url) == f"{BASE_URL}/"


# ---------------------------------------------------------------- parsing
async def test_fenced_json_output_is_parsed() -> None:
    server = Server(completion(f"```json\n{LAPTOP_JSON}\n```"))
    result = await build(server).extract(make_input())
    assert isinstance(result, ExtractionResult)
    assert result.attributes["ram_gb"] == 16


async def test_invalid_output_twice_is_an_invalid_output_rejection() -> None:
    server = Server(completion("nope"), completion("still nope"))
    result = await build(server).extract(make_input())
    assert isinstance(result, ExtractionRejection)
    assert result.kind is RejectionKind.INVALID_OUTPUT
    assert not result.retryable
    assert len(server.requests) == 2


async def test_bad_request_downgrades_to_json_object_for_later_calls() -> None:
    server = Server(bad_request(), completion(LAPTOP_JSON), completion(LAPTOP_JSON))
    extractor = build(server)
    assert isinstance(await extractor.extract(make_input()), ExtractionResult)
    assert extractor.structured_output is StructuredOutput.JSON_OBJECT
    assert server.body(0)["response_format"]["type"] == "json_schema"
    assert server.body(1)["response_format"] == {"type": "json_object"}
    await extractor.extract(make_input())
    assert server.body(2)["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------- error mapping
@pytest.mark.parametrize(
    ("reply", "kind"),
    [
        (httpx.ReadTimeout("slow"), RejectionKind.TRANSIENT),
        (httpx.Response(429, json={"error": "x"}), RejectionKind.TRANSIENT),
        (httpx.Response(408, json={"error": "x"}), RejectionKind.TRANSIENT),
        (httpx.Response(500, json={"error": "x"}), RejectionKind.TRANSIENT),
        (httpx.Response(503, json={"error": "x"}), RejectionKind.TRANSIENT),
        (httpx.ConnectError("down"), RejectionKind.UNAVAILABLE),
        (httpx.Response(402, json={"error": "x"}), RejectionKind.QUOTA),
    ],
)
async def test_retryable_errors(reply: httpx.Response | Exception, kind: RejectionKind) -> None:
    result = await build(Server(reply)).extract(make_input())
    assert isinstance(result, ExtractionRejection)
    assert result.retryable
    assert result.kind is kind


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, RejectionKind.UNAVAILABLE),
        (403, RejectionKind.UNAVAILABLE),
        (404, RejectionKind.UNAVAILABLE),
        (422, RejectionKind.PERMANENT),
    ],
)
async def test_client_errors_are_not_retryable(status: int, kind: RejectionKind) -> None:
    result = await build(Server(httpx.Response(status, json={"error": "x"}))).extract(make_input())
    assert isinstance(result, ExtractionRejection)
    assert not result.retryable
    assert result.kind is kind


# ---------------------------------------------------------------- health check
async def test_check_model_listed() -> None:
    server = Server(models("other", MODEL))
    health = await build(server).check()
    assert health.ok
    assert health.model_available is True
    assert str(server.requests[0].url) == f"{BASE_URL}/models"
    assert server.requests[0].method == "GET"


async def test_check_model_not_listed_names_what_is_available() -> None:
    health = await build(Server(models("a", "b"))).check()
    assert not health.ok
    assert health.model_available is False
    assert MODEL in health.detail
    assert "a, b" in health.detail


async def test_check_unreachable_server() -> None:
    health = await build(Server(httpx.ConnectError("refused"))).check()
    assert not health.ok
    assert "cannot reach" in health.detail


async def test_check_http_error() -> None:
    health = await build(Server(httpx.Response(500, json={"error": "x"}))).check()
    assert not health.ok
    assert "HTTP 500" in health.detail


async def test_check_authentication_failure_hints_the_key_variable() -> None:
    server = Server(httpx.Response(401, json={"error": "x"}))
    health = await build(server, key_hint="MY_KEY").check()
    assert not health.ok
    assert "MY_KEY" in health.detail


# ---------------------------------------------------------------- probe
async def test_probe_keeps_json_schema_when_accepted() -> None:
    server = Server(models(MODEL), completion('{"category": "laptop", "attributes": {}}'))
    health = await build(server).check(probe=True)
    assert health.ok
    assert health.effective_structured_output is StructuredOutput.JSON_SCHEMA


async def test_probe_downgrades_to_json_object() -> None:
    server = Server(models(MODEL), bad_request(), completion("{}"))
    extractor = build(server)
    health = await extractor.check(probe=True)
    assert health.effective_structured_output is StructuredOutput.JSON_OBJECT
    assert extractor.structured_output is StructuredOutput.JSON_OBJECT
    assert server.body(2)["response_format"] == {"type": "json_object"}


async def test_probe_downgrades_to_prompt_only() -> None:
    server = Server(models(MODEL), bad_request(), bad_request(), completion("{}"))
    extractor = build(server)
    health = await extractor.check(probe=True)
    assert health.effective_structured_output is StructuredOutput.PROMPT_ONLY
    assert "response_format" not in server.body(3)


async def test_probe_downgrades_when_the_answer_is_not_json() -> None:
    server = Server(models(MODEL), completion("sorry, no"), completion("{}"))
    health = await build(server).check(probe=True)
    assert health.effective_structured_output is StructuredOutput.JSON_OBJECT


async def test_probe_keeps_the_level_on_transport_failure() -> None:
    server = Server(models(MODEL), httpx.ConnectError("down"))
    health = await build(server).check(probe=True)
    assert health.effective_structured_output is StructuredOutput.JSON_SCHEMA
