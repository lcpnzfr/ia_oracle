"""Sample usages for :mod:`ia_oracle.providers.ia_service_openai`.

The functions in this module are intentionally example-oriented and are not
called by the production Oracle pipeline. They demonstrate how applications can
reuse ``IAServiceOpenAI`` for modern Responses API workflows: reasoning models,
structured outputs, web/file search tools, image/vision inputs, streaming,
function-tool loops, response continuation, and FastAPI-style lifecycle wiring.

Prerequisites for live examples::

    export OPENAI_API_KEY="..."
    python -m ia_oracle.providers.ia_service_openai_samples basic

Most examples call the OpenAI API. Keep them as copy-pasteable recipes and run
only the examples you need.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

from ia_oracle.providers.ia_service_openai import (
    IAServiceOpenAI,
    OpenAIResponseOptions,
    OpenAIServiceConfig,
    OpenAIWebSearchConfig,
)

DEFAULT_SAMPLE_MODEL = "gpt-5.5"
FAST_SAMPLE_MODEL = "gpt-5.4-mini"
VISION_SAMPLE_MODEL = "gpt-5.4"


def make_service() -> IAServiceOpenAI:
    """Create a shared service with sensible sample defaults."""

    return IAServiceOpenAI(
        OpenAIServiceConfig(
            concurrency=4,
            default_options=OpenAIResponseOptions(
                model=DEFAULT_SAMPLE_MODEL,
                fallback_models=("gpt-5.4", "gpt-5.4-mini", "gpt-4.1"),
                max_output_tokens=1600,
                reasoning_effort="medium",
                text_verbosity="medium",
                temperature=0.2,
            ),
        )
    )


async def basic_reasoning_example() -> None:
    """Use a frontier reasoning model for a concise macro/FX analysis."""

    async with make_service() as service:
        result = await service.generate(
            "Explain how a surprise Bank of Japan hike can transmit to USDJPY, "
            "Japanese equities, and global risk sentiment. Keep it concise.",
            instructions="You are a senior macro strategist. Use bullet points.",
            reasoning_effort="high",
            max_output_tokens=900,
        )
        print(result.text)


async def structured_oracle_decision_example() -> None:
    """Request strict JSON conforming to an application schema."""

    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "confidence", "affected_assets", "rationale"],
        "properties": {
            "action": {"type": "string", "enum": ["EMIT", "HOLD", "DISCARD"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "affected_assets": {
                "type": "array",
                "items": {"type": "string"},
            },
            "rationale": {"type": "string"},
        },
    }
    options = OpenAIResponseOptions(
        model=DEFAULT_SAMPLE_MODEL,
        json_schema=schema,
        json_schema_name="oracle_sample_decision",
        reasoning_effort="medium",
        max_output_tokens=800,
    )

    async with make_service() as service:
        result = await service.generate(
            "Headline: US CPI prints 0.4pp above consensus while Fed speakers "
            "signal patience. Decide whether to emit a macro GlobalTag.",
            instructions="Return only the structured decision.",
            options=options,
        )
        print(json.dumps(json.loads(result.text), indent=2))


async def web_search_example() -> None:
    """Enable OpenAI-hosted web search with domain filters and source capture."""

    options = OpenAIResponseOptions(
        model=DEFAULT_SAMPLE_MODEL,
        web_search=OpenAIWebSearchConfig(
            enabled=True,
            search_context_size="medium",
            allowed_domains=("federalreserve.gov", "ecb.europa.eu", "boj.or.jp"),
            user_location={"country": "US", "city": "New York", "region": "NY"},
            include_sources=True,
        ),
        max_output_tokens=1200,
    )

    async with make_service() as service:
        result = await service.generate(
            "Find the latest official central-bank policy communications from "
            "the Fed, ECB, and BoJ and summarize only policy-sensitive signals.",
            options=options,
        )
        print(result.text)


async def remote_image_vision_example() -> None:
    """Send an image URL plus text for vision/chart interpretation."""

    input_payload: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Describe the image, then list any market-relevant "
                    "signals if this were a financial chart screenshot.",
                },
                {
                    "type": "input_image",
                    "image_url": "https://upload.wikimedia.org/wikipedia/commons/3/3f/Fronalpstock_big.jpg",
                },
            ],
        }
    ]

    async with make_service() as service:
        result = await service.generate(
            input_payload,
            model=VISION_SAMPLE_MODEL,
            instructions="Be precise. Separate observations from interpretation.",
            max_output_tokens=900,
        )
        print(result.text)


async def local_image_vision_example(image_path: Path) -> None:
    """Send a local image as a data URL for OCR/vision analysis."""

    encoded_image = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    suffix = image_path.suffix.lower().lstrip(".") or "png"
    mime_type = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
    data_url = f"data:image/{mime_type};base64,{encoded_image}"
    input_payload = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "OCR this image and summarize key facts."},
                {"type": "input_image", "image_url": data_url},
            ],
        }
    ]

    async with make_service() as service:
        result = await service.generate(input_payload, model=VISION_SAMPLE_MODEL)
        print(result.text)


async def streaming_example() -> None:
    """Stream raw Responses API events for CLI or Server-Sent Events adapters."""

    options = OpenAIResponseOptions(model=FAST_SAMPLE_MODEL, max_output_tokens=700)
    async with make_service() as service:
        async for event in service.stream(
            "Write a short operational checklist for releasing an Oracle worker.",
            options=options,
        ):
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                print(getattr(event, "delta", ""), end="", flush=True)
        print()


def current_fx_snapshot(pair: str) -> Mapping[str, Any]:
    """Tiny fake application function used by the tool-calling sample."""

    snapshots = {
        "USDJPY": {"spot": 157.42, "one_day_change_pct": 0.38, "risk": "intervention watch"},
        "EURUSD": {"spot": 1.0831, "one_day_change_pct": -0.14, "risk": "ECB repricing"},
    }
    return snapshots.get(pair.upper(), {"spot": None, "risk": "unknown pair"})


async def function_tool_loop_example() -> None:
    """Show the standard model -> function call -> tool output -> final answer loop."""

    tool = {
        "type": "function",
        "name": "current_fx_snapshot",
        "description": "Return a small current-market snapshot for an FX pair.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["pair"],
            "properties": {"pair": {"type": "string", "description": "FX pair, e.g. USDJPY"}},
        },
        "strict": True,
    }
    options = OpenAIResponseOptions(
        model=DEFAULT_SAMPLE_MODEL,
        tools=(tool,),
        tool_choice="auto",
        max_output_tokens=900,
    )

    async with make_service() as service:
        first = await service.generate(
            "Use available tools to assess whether USDJPY risk is elevated today.",
            options=options,
        )
        response_output = getattr(first.response, "output", []) or []
        follow_up_input: list[dict[str, Any]] = []
        for item in response_output:
            if getattr(item, "type", None) != "function_call":
                continue
            args = json.loads(getattr(item, "arguments", "{}"))
            tool_result = current_fx_snapshot(str(args.get("pair", "USDJPY")))
            follow_up_input.append(
                {
                    "type": "function_call_output",
                    "call_id": getattr(item, "call_id"),
                    "output": json.dumps(tool_result),
                }
            )

        if not follow_up_input:
            print(first.text)
            return

        final = await service.generate(
            follow_up_input,
            options=OpenAIResponseOptions(
                model=DEFAULT_SAMPLE_MODEL,
                previous_response_id=first.response_id,
                max_output_tokens=900,
            ),
        )
        print(final.text)


async def file_search_example(vector_store_id: str) -> None:
    """Use an existing OpenAI vector store through the hosted file_search tool."""

    options = OpenAIResponseOptions(
        model=DEFAULT_SAMPLE_MODEL,
        tools=(
            {
                "type": "file_search",
                "vector_store_ids": [vector_store_id],
                "max_num_results": 5,
            },
        ),
        max_output_tokens=1200,
    )

    async with make_service() as service:
        result = await service.generate(
            "Search the knowledge base for OracleWorker deployment constraints "
            "and return a release-risk checklist.",
            options=options,
        )
        print(result.text)


async def conversation_continuation_example() -> None:
    """Continue from a previous response without resending all prior context."""

    async with make_service() as service:
        first = await service.generate(
            "Create a three-point thesis for why geopolitics can move gold.",
            model=FAST_SAMPLE_MODEL,
            max_output_tokens=500,
        )
        second = await service.generate(
            "Now convert that thesis into risk-manager action items.",
            options=OpenAIResponseOptions(
                model=FAST_SAMPLE_MODEL,
                previous_response_id=first.response_id,
                max_output_tokens=500,
            ),
        )
        print(second.text)


async def fastapi_lifespan_sketch() -> AsyncIterator[IAServiceOpenAI]:
    """Minimal FastAPI-style lifespan/dependency sketch.

    Copy this pattern into an app module and yield the service from the app
    lifespan. It is kept framework-free so importing this sample does not add a
    FastAPI dependency to ``ia_oracle``.
    """

    service = make_service()
    try:
        yield service
    finally:
        await service.close()


async def _run_sample(args: argparse.Namespace) -> None:
    samples = {
        "basic": basic_reasoning_example,
        "structured": structured_oracle_decision_example,
        "web": web_search_example,
        "remote-image": remote_image_vision_example,
        "stream": streaming_example,
        "function-tool": function_tool_loop_example,
        "continue": conversation_continuation_example,
    }
    if args.sample == "local-image":
        await local_image_vision_example(Path(args.image_path).expanduser())
    elif args.sample == "file-search":
        await file_search_example(args.vector_store_id)
    else:
        await samples[args.sample]()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run IAServiceOpenAI examples.")
    parser.add_argument(
        "sample",
        choices=(
            "basic",
            "structured",
            "web",
            "remote-image",
            "local-image",
            "stream",
            "function-tool",
            "file-search",
            "continue",
        ),
        help="Example to run.",
    )
    parser.add_argument("--image-path", default="sample.png", help="Path for local-image.")
    parser.add_argument(
        "--vector-store-id",
        default="vs_replace_me",
        help="Existing vector store id for file-search.",
    )
    return parser


if __name__ == "__main__":
    asyncio.run(_run_sample(_build_parser().parse_args()))
