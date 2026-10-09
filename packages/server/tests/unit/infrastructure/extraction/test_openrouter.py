from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from scrappy.application.ports.extractor import ExtractionRejection, ExtractionResult
from scrappy.domain.category import OTHER_CATEGORY
from scrappy.domain.extraction import OfferExtraction
from scrappy.infrastructure.extraction.openrouter import OpenRouterAttributeExtractor
from scrappy.infrastructure.extraction.prompt import PROMPT_VERSION
from tests.unit.builders import LAPTOP, T0, catalog

from .conftest import HASH, make_input


def completion(content: str, prompt: int = 100, completion_tokens: int = 20) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "x",
            "object": "chat.completion",
            "created": 1,
            "model": "test/model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {
                "prompt_tokens": prompt,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt + completion_tokens,
                "cost": 0.00042,
            },
        },
    )


class Server:
    def __init__(self, *replies: httpx.Response | Exception) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def extractor(server: Server) -> OpenRouterAttributeExtractor:
    client = AsyncOpenAI(
        api_key="k",
        base_url="https://openrouter.test/api/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(server)),  # pyright: ignore[reportArgumentType]
        max_retries=0,
    )
    return OpenRouterAttributeExtractor(api_key="k", model="test/model", client=client)


LAPTOP_JSON = json.dumps(
    {
        "category": "laptop",
        "attributes": {"gpu": "GTX 1650", "ram_gb": 16, "screen_in": 15.6, "storage_type": "ssd"},
        "notes": None,
    }
)


async def test_valid_response_with_provenance_and_usage() -> None:
    server = Server(completion(LAPTOP_JSON, 120, 30))
    result = await extractor(server).extract(make_input())
    assert isinstance(result, ExtractionResult)
    assert result.category == LAPTOP
    assert result.model == "test/model"
    assert result.prompt_version == PROMPT_VERSION
    assert result.usage.prompt_tokens == 120
    assert result.usage.completion_tokens == 30
    assert result.usage.cost_usd == Decimal("0.00042")
    body = server.requests[0]
    assert body["response_format"]["type"] == "json_schema"
    assert body["messages"][0]["role"] == "system"
    assert body["usage"] == {"include": True}
    extraction = OfferExtraction.validated(  # the domain accepts the result as is
        offer_id=make_input().offer_id,
        category=result.category,
        raw_attributes=result.attributes,
        catalog=catalog(),
        model=result.model,
        prompt_version=result.prompt_version,
        content_hash=HASH,
        extracted_at=T0,
        usage=result.usage,
    )
    assert extraction.attributes["screen_in"] == Decimal("15.6")
    assert extraction.provenance.schema_version == 1


def test_client_configured_for_openrouter() -> None:
    ex = OpenRouterAttributeExtractor(
        api_key="k", model="m", referer="https://me.test", app_title="scrappy"
    )
    client = ex._client  # pyright: ignore[reportPrivateUsage]
    assert client.default_headers["HTTP-Referer"] == "https://me.test"
    assert client.default_headers["X-Title"] == "scrappy"
    assert str(client.base_url).startswith("https://openrouter.ai/api/v1")
    assert client.max_retries == 0


async def test_unknown_category_maps_to_other() -> None:
    server = Server(completion('{"category": "spaceship", "attributes": {"a": 1}, "notes": "x"}'))
    result = await extractor(server).extract(make_input())
    assert isinstance(result, ExtractionResult)
    assert result.category == OTHER_CATEGORY
    assert dict(result.attributes) == {}


async def test_invalid_json_then_corrected_sums_usage() -> None:
    server = Server(completion("not json at all", 100, 10), completion(LAPTOP_JSON, 150, 20))
    result = await extractor(server).extract(make_input())
    assert isinstance(result, ExtractionResult)
    assert result.usage.prompt_tokens == 250
    assert result.usage.completion_tokens == 30
    assert len(server.requests) == 2
    retry_messages = server.requests[1]["messages"]
    assert retry_messages[-2] == {"role": "assistant", "content": "not json at all"}
    assert "not valid JSON" in retry_messages[-1]["content"]


async def test_fenced_json_is_accepted() -> None:
    server = Server(completion(f"```json\n{LAPTOP_JSON}\n```"))
    assert isinstance(await extractor(server).extract(make_input()), ExtractionResult)


async def test_invalid_twice_is_non_retryable_rejection_with_usage() -> None:
    bad = '{"category": "laptop", "attributes": {"ram_gb": "lots"}}'
    server = Server(completion(bad, 100, 10), completion(bad, 100, 10))
    result = await extractor(server).extract(make_input())
    assert isinstance(result, ExtractionRejection)
    assert not result.retryable
    assert "ram_gb" in result.reason
    assert result.usage.total_tokens == 220
    assert result.model == "test/model"
    assert len(server.requests) == 2


async def test_numeric_string_is_passed_raw_for_domain_coercion() -> None:
    server = Server(
        completion('{"category": "laptop", "attributes": {"ram_gb": "16"}, "notes": null}')
    )
    result = await extractor(server).extract(make_input())
    assert isinstance(result, ExtractionResult)
    assert result.attributes == {"ram_gb": "16"}  # the domain coerces to 16


async def test_429_is_retryable() -> None:
    server = Server(httpx.Response(429, json={"error": {"message": "slow down"}}))
    result = await extractor(server).extract(make_input())
    assert isinstance(result, ExtractionRejection)
    assert result.retryable
    assert "429" in result.reason


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_5xx_is_retryable(status: int) -> None:
    result = await extractor(Server(httpx.Response(status, json={"error": "x"}))).extract(
        make_input()
    )
    assert isinstance(result, ExtractionRejection)
    assert result.retryable


async def test_401_is_not_retryable() -> None:
    result = await extractor(Server(httpx.Response(401, json={"error": "no key"}))).extract(
        make_input()
    )
    assert isinstance(result, ExtractionRejection)
    assert not result.retryable


@pytest.mark.parametrize("error", [httpx.ReadTimeout("slow"), httpx.ConnectError("down")])
async def test_timeout_and_connection_errors_are_retryable(error: Exception) -> None:
    result = await extractor(Server(error)).extract(make_input())
    assert isinstance(result, ExtractionRejection)
    assert result.retryable


async def test_falls_back_to_json_object_when_schema_unsupported() -> None:
    server = Server(
        httpx.Response(400, json={"error": {"message": "response_format unsupported"}}),
        completion(LAPTOP_JSON),
        completion(LAPTOP_JSON),
    )
    ex = extractor(server)
    first = await ex.extract(make_input())
    assert isinstance(first, ExtractionResult)
    assert server.requests[0]["response_format"]["type"] == "json_schema"
    assert server.requests[1]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in server.requests[1]["messages"][1]["content"]
    await ex.extract(make_input())  # remembered: straight to json_object
    assert server.requests[2]["response_format"] == {"type": "json_object"}


async def test_empty_choices_is_invalid_output() -> None:
    empty = httpx.Response(
        200,
        json={"id": "x", "object": "chat.completion", "created": 1, "model": "m", "choices": []},
    )
    result = await extractor(Server(empty, empty)).extract(make_input())
    assert isinstance(result, ExtractionRejection)
    assert not result.retryable


FIXTURE = (
    Path(__file__).resolve().parents[5]
    / "docs/research/olx_pl_fixtures/api_offer_detail_long_description.json"
)


@pytest.mark.live
async def test_live_openrouter_long_description() -> None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        pytest.skip("OPENROUTER_API_KEY not set")
    from scrappy.application.extraction.prepare import prepare_description

    data = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]
    text, _ = prepare_description(data["description"], 4000)
    request = make_input(description=text, title=data["title"])
    model = os.environ.get("SCRAPPY_LLM_MODEL", "openai/gpt-4o-mini")
    result = await OpenRouterAttributeExtractor(api_key=key, model=model).extract(request)
    assert isinstance(result, ExtractionResult), result
    assert result.category == LAPTOP
    assert result.usage.total_tokens > 0
