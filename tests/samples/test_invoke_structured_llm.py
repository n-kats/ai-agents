from __future__ import annotations

import asyncio
import os

import pytest

from nkaa.presets.tools import LLMCallTool
from samples.llm_delegation import StructuredChannelResponse, invoke_structured_llm


@pytest.mark.live_api
def test_invoke_structured_llm_calls_openai_api() -> None:
    pytest.importorskip("openai")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY is not configured")

    tool = LLMCallTool(api_key=api_key, default_model="gpt-5-mini")

    payload = {
        "incoming_channel": {
            "channel_id": "channel_1",
            "channel_name": "human_support",
            "channel_description": "user facing channel",
        },
        "incoming_message": {
            "role": "human",
            "content": "Respond with the exact content 'LIVE_API_OK'.",
        },
        "available_channels": [
            {
                "channel_name": "human_support",
                "channel_description": "user facing channel",
            },
        ],
    }

    response = asyncio.run(
        invoke_structured_llm(
            tool,
            model="gpt-5-mini",
            system_prompt=(
                "You are a relay agent. Always produce a StructuredChannelResponse "
                "that routes messages back to 'human_support'. "
                "Set message.role to 'reply' and message.content to exactly 'LIVE_API_OK'."
            ),
            payload=payload,
            log=None,
        )
    )

    assert isinstance(response, StructuredChannelResponse)
    assert response.output_channel == "human_support"
    assert response.message.role == "reply"
    assert "LIVE_API_OK" in response.message.content
