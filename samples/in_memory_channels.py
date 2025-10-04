"""StandardManager を利用した InMemory チャネル協調サンプル。"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Type, cast

from pydantic import BaseModel, Field

from nkaa.framework.agent import (
    AgentConfig,
    BaseAgent,
    BaseTools,
    StandardManager,
    StandardManagerConfig,
    ThreadingManagerExecutionBackend,
)
from nkaa.framework.channels import (
    ChannelManager,
    ChannelSearchQuery,
    DatabaseChannelConfig,
    InMemoryChannelRepository,
)
from nkaa.framework.channels.models import UnreadRecord
from nkaa.framework.logging import AgentLogTool, configure_logging
from nkaa.framework.tools import ChannelTools

# ---------------------------------------------------------------------------
# ツール定義
# ---------------------------------------------------------------------------


@dataclass
class DemoManagerTools(BaseTools):
    channel_manager: ChannelManager
    stop_manager: Callable[[], None] | None = None

    def stop(self) -> None:
        return None

    def save(self) -> None:
        return None


@dataclass
class DemoAgentTools(BaseTools):
    channels: ChannelTools
    log: AgentLogTool
    stop_manager: Callable[[], None] | None = None

    def stop(self) -> None:
        return None

    def save(self) -> None:
        return None


def demo_adapter(agent: BaseAgent[DemoAgentTools], manager_tools: DemoManagerTools) -> DemoAgentTools:
    channel_tools = ChannelTools(agent_id=agent.agent_id, manager=manager_tools.channel_manager)
    log_tool = AgentLogTool(agent_id=agent.agent_id)
    return DemoAgentTools(
        channels=channel_tools,
        log=log_tool,
        stop_manager=manager_tools.stop_manager,
    )


# ---------------------------------------------------------------------------
# エージェント実装
# ---------------------------------------------------------------------------


class ChannelDescriptor(BaseModel):
    name: str
    description: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    def to_config(self) -> DatabaseChannelConfig:
        return DatabaseChannelConfig(
            name=self.name,
            description=self.description,
            attributes=self.attributes,
        )


class BaseDemoAgent(BaseAgent[DemoAgentTools]):
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id

    def stop(self) -> None:
        return None

    def load(self) -> None:
        return None

    def save(self) -> None:
        return None


class AlertPublisher(BaseDemoAgent):
    """チャネルを生成し、メッセージを投稿するエージェント。"""

    def __init__(
        self,
        agent_id: str,
        channel: ChannelDescriptor,
        payloads: Iterable[dict[str, Any]],
    ) -> None:
        super().__init__(agent_id)
        self.channel_descriptor = channel
        self.payloads = list(payloads)
        self.channel_id: str | None = None

    def run(self, tools: DemoAgentTools) -> None:
        if self.channel_id is None:
            self.channel_id = self._ensure_channel(tools)

        tools.channels.join(self.channel_id)
        log = tools.log.logger
        channel_id = self.channel_id
        with tools.log.context(channel_id=channel_id):
            for payload in self.payloads:
                stored = tools.channels.send(channel_id, payload)
                log.info(
                    "sent message",
                    message_id=stored.message_id,
                    payload=stored.payload,
                )

    def _ensure_channel(self, tools: DemoAgentTools) -> str:
        descriptor = self.channel_descriptor
        existing = tools.channels.search(ChannelSearchQuery(name=descriptor.name))
        if existing:
            channel_id = existing[0].id
        else:
            channel = tools.channels.manager.create(descriptor.to_config())
            channel_id = channel.id
            metadata = channel.metadata
            tools.log.logger.info(
                "created channel",
                channel_id=metadata.id,
                name=metadata.name,
                attributes=metadata.attributes,
            )
        return channel_id


class AlertSubscriber(BaseDemoAgent):
    """メタデータ検索でチャネルに参加し、未読を処理するエージェント。"""

    def __init__(
        self,
        agent_id: str,
        query: ChannelSearchQuery,
        *,
        read_timeout: float = 0.2,
        max_idle_cycles: int = 5,
    ) -> None:
        super().__init__(agent_id)
        self.query = query
        self.joined = False
        self.read_timeout = read_timeout
        self.max_idle_cycles = max_idle_cycles

    def run(self, tools: DemoAgentTools) -> None:
        log = tools.log.logger
        if not self.joined:
            joined = tools.channels.join_matching(self.query)
            if joined:
                log.info("joined channels", joined=joined)
                self.joined = True

        idle_cycles = 0
        while idle_cycles < self.max_idle_cycles:
            message = tools.channels.read(block=True, timeout=self.read_timeout)
            if message is None:
                idle_cycles += 1
                newly_joined = tools.channels.join_matching(self.query)
                if newly_joined:
                    log.info("joined channels", joined=newly_joined)
                    self.joined = True
                continue

            idle_cycles = 0
            with tools.log.context(channel_id=message.channel_id):
                log.info(
                    "received message",
                    message_id=message.message_id,
                    payload=message.payload,
                )


class SnapshotObserver(BaseDemoAgent):
    """未読スナップショットと復元を確認するエージェント。"""

    def __init__(
        self,
        agent_id: str,
        target_agent_id: str,
        *,
        wait_before_snapshot: float = 0.3,
    ) -> None:
        super().__init__(agent_id)
        self.target_agent_id = target_agent_id
        self.wait_before_snapshot = wait_before_snapshot

    def run(self, tools: DemoAgentTools) -> None:
        if self.wait_before_snapshot > 0:
            time.sleep(self.wait_before_snapshot)
        manager = tools.channels.manager
        records = manager.snapshot_unread_records(self.target_agent_id)
        with tools.log.context(target_agent=self.target_agent_id):
            self._log_records(tools, records)

        manager.repository.replace_unread_records(records)

        restored_manager = ChannelManager(manager.repository)
        restored_message = restored_manager.read_for_agent(self.target_agent_id)
        tools.log.logger.info("restored message", message=restored_message)

        if callable(tools.stop_manager):
            tools.stop_manager()

    def _log_records(self, tools: DemoAgentTools, records: list[UnreadRecord]) -> None:
        tools.log.logger.info("snapshot captured", count=len(records))
        for record in records:
            tools.log.logger.debug(
                "snapshot record",
                agent_id=record.agent_id,
                channel_id=record.channel_id,
                message_id=record.message_id,
                priority=record.priority,
            )


# ---------------------------------------------------------------------------
# AgentConfig 実装
# ---------------------------------------------------------------------------


class PublisherAgentConfig(AgentConfig):
    type: Literal["alert_publisher"] = "alert_publisher"
    channel: ChannelDescriptor
    payloads: list[dict[str, Any]] = Field(default_factory=list)

    def build(self) -> AlertPublisher:
        return AlertPublisher(agent_id=self.id, channel=self.channel, payloads=self.payloads)


class SubscriberAgentConfig(AgentConfig):
    type: Literal["alert_subscriber"] = "alert_subscriber"
    query: ChannelSearchQuery
    read_timeout: float = 0.2
    max_idle_cycles: int = 5

    def build(self) -> AlertSubscriber:
        return AlertSubscriber(
            agent_id=self.id,
            query=self.query,
            read_timeout=self.read_timeout,
            max_idle_cycles=self.max_idle_cycles,
        )


class ObserverAgentConfig(AgentConfig):
    type: Literal["snapshot_observer"] = "snapshot_observer"
    target_agent_id: str
    wait_before_snapshot: float = 0.3

    def build(self) -> SnapshotObserver:
        return SnapshotObserver(
            agent_id=self.id,
            target_agent_id=self.target_agent_id,
            wait_before_snapshot=self.wait_before_snapshot,
        )


AGENT_TYPE_REGISTRY: dict[str, Type[AgentConfig]] = {
    "alert_publisher": PublisherAgentConfig,
    "alert_subscriber": SubscriberAgentConfig,
    "snapshot_observer": ObserverAgentConfig,
}


class DemoManagerConfig(StandardManagerConfig):
    config_dir: Path

    def get_agent_config_paths(self) -> list[Path]:
        return sorted(self.config_dir.glob("*.json"))

    def get_agent_config_type(self, type_name: str) -> Type[AgentConfig]:
        try:
            return AGENT_TYPE_REGISTRY[type_name]
        except KeyError as exc:
            raise ValueError(f"Unknown agent type: {type_name}") from exc

    def build_tools(self) -> DemoManagerTools:
        return DemoManagerTools(channel_manager=ChannelManager(InMemoryChannelRepository()))


# ---------------------------------------------------------------------------
# 設定ファイル生成とデモ実行
# ---------------------------------------------------------------------------


def _write_config(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def prepare_configs(base_dir: Path) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)

    configs = [
        (
            "01_publisher_bootstrap.json",
            {
                "type": "alert_publisher",
                "id": "publisher_bootstrap",
                "channel": {
                    "name": "alerts",
                    "description": "Operations alert feed",
                    "attributes": {"topic": "ops", "level": "high"},
                },
                "payloads": [],
            },
        ),
        (
            "02_subscriber.json",
            {
                "type": "alert_subscriber",
                "id": "subscriber",
                "query": {"attributes": {"topic": "ops"}},
            },
        ),
        (
            "03_publisher_main.json",
            {
                "type": "alert_publisher",
                "id": "publisher_main",
                "channel": {
                    "name": "alerts",
                    "description": "Operations alert feed",
                    "attributes": {"topic": "ops", "level": "high"},
                },
                "payloads": [
                    {"text": "CPU usage exceeded 90%"},
                    {"text": "Disk space below 10%"},
                    {"text": "Service restarted"},
                ],
            },
        ),
        (
            "04_publisher_followup.json",
            {
                "type": "alert_publisher",
                "id": "publisher_followup",
                "channel": {
                    "name": "alerts",
                    "description": "Operations alert feed",
                    "attributes": {"topic": "ops", "level": "high"},
                },
                "payloads": [{"text": "Escalation ticket opened"}],
            },
        ),
        (
            "05_observer.json",
            {
                "type": "snapshot_observer",
                "id": "observer",
                "target_agent_id": "subscriber",
                "wait_before_snapshot": 0.5,
            },
        ),
    ]

    for filename, data in configs:
        _write_config(base_dir / filename, data)


def run_demo() -> None:
    state = configure_logging(enable_console=True, buffer_limit=200)
    manager_logger = AgentLogTool(agent_id="manager").logger
    manager_logger.info("logging configured", state=state)
    config_dir = Path("_tmp/samples/standard_manager")
    prepare_configs(config_dir)

    manager = StandardManager.initialize_or_load(
        config_dir,
        config_factory=lambda storage_dir: DemoManagerConfig(config_dir=storage_dir),
        adapter=demo_adapter,
        execution_backend=ThreadingManagerExecutionBackend(),
    )

    tools = cast(DemoManagerTools, manager.tools)
    tools.stop_manager = manager.create_stop_event_tool()

    manager.run()


if __name__ == "__main__":
    run_demo()
