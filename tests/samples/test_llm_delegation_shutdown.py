from __future__ import annotations

import asyncio
from typing import Any


from nkaa.framework.channels.models import ChannelMessage, ChannelMetadata
from nkaa.framework.logging import AgentLogTool
from nkaa.framework.messages import StopMessage
from samples.llm_delegation import (
    DelegationLLMAgent,
    StructuredChannelMessage,
    StructuredChannelResponse,
)


class DummyChannels:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[ChannelMessage] = asyncio.Queue()
        self.sent: list[tuple[str, Any]] = []
        self._metadata = (
            ChannelMetadata(id="analysis", name="analysis_workspace"),
            ChannelMetadata(id="human", name="human_support"),
        )

    def queue_message(self, message: ChannelMessage) -> None:
        self._queue.put_nowait(message)

    async def read_async(
        self,
        *,
        poll_interval: float = 0.05,
        stop_event: asyncio.Event | None = None,
        allowed_channels: list[str] | None = None,
    ) -> ChannelMessage | StopMessage | None:
        del allowed_channels
        while True:
            if stop_event is not None and stop_event.is_set():
                return StopMessage(reason="stop_event_set")
            try:
                message = self._queue.get_nowait()
                return message
            except asyncio.QueueEmpty:
                pass
            try:
                message = await asyncio.wait_for(self._queue.get(), timeout=poll_interval)
                return message
            except asyncio.TimeoutError:
                if stop_event is not None and stop_event.is_set():
                    return StopMessage(reason="stop_event_set")

    async def send_async(
        self,
        channel_id: str,
        payload: Any,
        *,
        priority: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChannelMessage:
        del priority, metadata
        self.sent.append((channel_id, payload))
        return ChannelMessage(
            channel_id=channel_id,
            sender_id="dummy",
            payload=payload,
        )

    def joined_channel_metadata(self) -> tuple[ChannelMetadata, ...]:
        return self._metadata


class DummyTools:
    def __init__(self, channels: DummyChannels, llm: "StubbornLLM", log: AgentLogTool) -> None:
        self.channels = channels
        self.messages = channels
        self.llm = llm
        self.log = log
        self.stop_manager = None

    def joined_channel_metadata(self) -> tuple[ChannelMetadata, ...]:
        return self.channels.joined_channel_metadata()


class StubbornLLM:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.release = asyncio.Event()

    async def call_parsed_async(self, *args: Any, **kwargs: Any) -> StructuredChannelResponse:
        del args, kwargs
        self.started.set()
        while not self.release.is_set():
            try:
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                self.cancelled.set()
        return StructuredChannelResponse(
            output_channel="analysis_workspace",
            message=StructuredChannelMessage(role="analysis_summary", content="done"),
        )


class RecordingLLM:
    def __init__(self) -> None:
        self.called = False

    async def call_parsed_async(self, *args: Any, **kwargs: Any) -> StructuredChannelResponse:
        del args, kwargs
        self.called = True
        return StructuredChannelResponse(
            output_channel="analysis_workspace",
            message=StructuredChannelMessage(role="analysis_summary", content="noop"),
        )


def test_delegation_agent_shutdown_times_out_on_stubborn_llm() -> None:
    asyncio.run(_run_shutdown_scenario())


async def _run_shutdown_scenario() -> None:
    channels = DummyChannels()
    llm = StubbornLLM()
    log_tool = AgentLogTool(agent_id="thinking_agent")
    tools = DummyTools(channels, llm, log_tool)
    agent = DelegationLLMAgent(
        agent_id="thinking_agent",
        system_prompt="system",
        model="gpt-5-mini",
        shutdown_grace_period=0.1,
    )

    channels.queue_message(
        ChannelMessage(
            channel_id="analysis",
            sender_id="front_desk_agent",
            payload={"role": "analysis_request", "content": "ping"},
        )
    )

    agent_task = asyncio.create_task(agent.run_async(tools))
    await asyncio.wait_for(llm.started.wait(), timeout=1.0)
    agent.stop()

    await asyncio.wait_for(agent_task, timeout=1.0)
    assert llm.cancelled.is_set()

    # テスト終了後に LLM 擬似タスクを解放してクリーンに終了させる
    llm.release.set()
    await asyncio.sleep(0)


def test_delegation_agent_stop_before_run_exits_early() -> None:
    asyncio.run(_run_stop_before_start_scenario())


async def _run_stop_before_start_scenario() -> None:
    channels = DummyChannels()
    llm = RecordingLLM()
    log_tool = AgentLogTool(agent_id="front_desk_agent")
    tools = DummyTools(channels, llm, log_tool)
    agent = DelegationLLMAgent(
        agent_id="front_desk_agent",
        system_prompt="system",
        model="gpt-5-mini",
        shutdown_grace_period=0.1,
    )

    agent.stop()

    await asyncio.wait_for(agent.run_async(tools), timeout=0.5)

    assert not llm.called
