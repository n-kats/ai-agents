"""StandardManager を利用した InMemory チャネル協調サンプル。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Type
import threading

from pydantic import BaseModel, Field

from nkaa.framework.agent import AgentConfig, BaseAgent, BaseTools, StandardManager, StandardManagerConfig
from nkaa.framework.channels import (
    ChannelManager,
    ChannelSearchQuery,
    DatabaseChannelConfig,
    InMemoryChannelRepository,
)
from nkaa.framework.channels.models import ChannelMetadata, UnreadRecord
from nkaa.framework.tools import ChannelTools

# multiprocessing.Event を利用できない環境向けに、StandardManager が参照する
# Event 実装を threading.Event へ差し替える。
import nkaa.framework.agent as agent_module

agent_module.Event = threading.Event


# ---------------------------------------------------------------------------
# ツール定義
# ---------------------------------------------------------------------------


@dataclass
class DemoManagerTools(BaseTools):
    channel_manager: ChannelManager

    def stop(self) -> None:
        return None

    def save(self) -> None:
        return None


@dataclass
class DemoAgentTools(BaseTools):
    channels: ChannelTools

    def stop(self) -> None:
        return None

    def save(self) -> None:
        return None


def demo_adapter(agent: BaseAgent[DemoAgentTools], manager_tools: DemoManagerTools) -> DemoAgentTools:
    channel_tools = ChannelTools(agent_id=agent.agent_id, manager=manager_tools.channel_manager)
    return DemoAgentTools(channels=channel_tools)


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
        for payload in self.payloads:
            stored = tools.channels.send(self.channel_id, payload)
            print(f"[Publisher:{self.agent_id}] sent #{stored.message_id}: {stored.payload}")

    def _ensure_channel(self, tools: DemoAgentTools) -> str:
        descriptor = self.channel_descriptor
        existing = tools.channels.search(ChannelSearchQuery(name=descriptor.name))
        if existing:
            channel_id = existing[0].id
        else:
            channel = tools.channels.manager.create(descriptor.to_config())
            channel_id = channel.id
            metadata = channel.metadata
            self._print_channel_created(metadata)
        return channel_id

    def _print_channel_created(self, metadata: ChannelMetadata) -> None:
        print(
            f"[Publisher:{self.agent_id}] created channel {metadata.id}"
            f" (name={metadata.name}, attributes={metadata.attributes})"
        )


class AlertSubscriber(BaseDemoAgent):
    """メタデータ検索でチャネルに参加し、未読を処理するエージェント。"""

    def __init__(self, agent_id: str, query: ChannelSearchQuery) -> None:
        super().__init__(agent_id)
        self.query = query
        self.joined = False

    def run(self, tools: DemoAgentTools) -> None:
        if not self.joined:
            joined = tools.channels.join_matching(self.query)
            print(f"[Subscriber] joined channels: {joined}")
            self.joined = True

        while True:
            message = tools.channels.read()
            if message is None:
                break
            print(f"[Subscriber] received #{message.message_id}: {message.payload}")


class SnapshotObserver(BaseDemoAgent):
    """未読スナップショットと復元を確認するエージェント。"""

    def __init__(self, agent_id: str, target_agent_id: str) -> None:
        super().__init__(agent_id)
        self.target_agent_id = target_agent_id

    def run(self, tools: DemoAgentTools) -> None:
        manager = tools.channels.manager
        records = manager.snapshot_unread_records(self.target_agent_id)
        self._print_records(records)

        manager.repository.replace_unread_records(records)

        restored_manager = ChannelManager(manager.repository)
        restored_message = restored_manager.read_for_agent(self.target_agent_id)
        print(f"[Observer] restored message: {restored_message}")

    def _print_records(self, records: list[UnreadRecord]) -> None:
        print(f"[Observer] unread snapshot count: {len(records)}")
        for record in records:
            print(
                "  ->",
                record.agent_id,
                record.channel_id,
                record.message_id,
                record.priority,
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

    def build(self) -> AlertSubscriber:
        return AlertSubscriber(agent_id=self.id, query=self.query)


class ObserverAgentConfig(AgentConfig):
    type: Literal["snapshot_observer"] = "snapshot_observer"
    target_agent_id: str

    def build(self) -> SnapshotObserver:
        return SnapshotObserver(agent_id=self.id, target_agent_id=self.target_agent_id)


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


class DemoManager(StandardManager[DemoManagerConfig, DemoManagerTools, DemoAgentTools]):
    def _load_tools(self) -> DemoManagerTools:
        repository = InMemoryChannelRepository()
        manager = ChannelManager(repository)
        return DemoManagerTools(channel_manager=manager)

    @classmethod
    def initialize_or_load(cls, storage_dir: Path) -> "DemoManager":
        config = DemoManagerConfig(config_dir=storage_dir)
        return cls(config, demo_adapter)


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
            },
        ),
    ]

    for filename, data in configs:
        _write_config(base_dir / filename, data)


def run_demo() -> None:
    config_dir = Path("_tmp/samples/standard_manager")
    prepare_configs(config_dir)

    manager = DemoManager.initialize_or_load(config_dir)

    agents = {getattr(agent, "agent_id", f"agent_{idx}"): agent for idx, agent in enumerate(manager.agents)}

    def run_agent(agent_id: str) -> None:
        agent = agents[agent_id]
        tools = manager.apply_adapter(agent)
        agent.run(tools)

    run_agent("publisher_bootstrap")
    run_agent("subscriber")
    run_agent("publisher_main")
    run_agent("subscriber")
    run_agent("publisher_followup")
    run_agent("observer")


if __name__ == "__main__":
    run_demo()
