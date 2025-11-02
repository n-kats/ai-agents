"""StandardManager を利用した SQLite チャネル永続化サンプル。"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Type, cast

from loguru import logger
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
    SQLChannelRepository,
)
from nkaa.framework.channels.message_routing import ChannelMessageRouteProvider
from nkaa.framework.channels.models import ChannelMessage, UnreadRecord
from nkaa.framework.logging import AgentLogTool, configure_logging
from nkaa.framework.message_manager import MessageManager
from nkaa.framework.tools import ChannelTools, MessageTools

# ---------------------------------------------------------------------------
# ツール定義
# ---------------------------------------------------------------------------


@dataclass
class SqlDemoManagerTools(BaseTools):
    channel_manager: ChannelManager
    message_manager: MessageManager
    stop_manager: Callable[[], None] | None = None

    def stop(self) -> None:
        return None

    def save(self) -> None:
        return None


@dataclass
class SqlDemoAgentTools(BaseTools):
    channels: ChannelTools
    messages: MessageTools
    log: AgentLogTool
    stop_manager: Callable[[], None] | None = None

    def stop(self) -> None:
        return None

    def save(self) -> None:
        return None


def demo_adapter(agent: BaseAgent[SqlDemoAgentTools], manager_tools: SqlDemoManagerTools) -> SqlDemoAgentTools:
    channel_tools = ChannelTools(agent_id=agent.agent_id, manager=manager_tools.channel_manager)
    message_tools = MessageTools(agent_id=agent.agent_id, manager=manager_tools.message_manager)
    log_tool = AgentLogTool(agent_id=agent.agent_id)
    if manager_tools.stop_manager is None:
        logger.warning("stop_manager tool is not configured for agent {}", agent.agent_id)
    return SqlDemoAgentTools(
        channels=channel_tools,
        messages=message_tools,
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


class BaseDemoAgent(BaseAgent[SqlDemoAgentTools]):
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
        *,
        delay_before_send: float = 0.0,
    ) -> None:
        super().__init__(agent_id)
        self.channel_descriptor = channel
        self.payloads = list(payloads)
        self.delay_before_send = delay_before_send
        self.channel_id: str | None = None

    def run(self, tools: SqlDemoAgentTools) -> None:
        if self.channel_id is None:
            self.channel_id = self._ensure_channel(tools)

        tools.channels.join(self.channel_id)
        log = tools.log.logger
        channel_id = self.channel_id
        with tools.log.context(channel_id=channel_id):
            if self.delay_before_send > 0:
                log.debug("sleep before send", delay=self.delay_before_send)
                time.sleep(self.delay_before_send)
            for payload in self.payloads:
                stored = tools.messages.send(channel_id, payload)
                log.info(
                    "sent message",
                    message_id=stored.message_id,
                    payload=stored.payload,
                )
        log.info("publisher finished", sent=len(self.payloads))

    def _ensure_channel(self, tools: SqlDemoAgentTools) -> str:
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


class LimitedSubscriber(BaseDemoAgent):
    """既読履歴を保存しつつ、受信件数を制限するエージェント。"""

    def __init__(
        self,
        agent_id: str,
        query: ChannelSearchQuery,
        history_path: Path,
        *,
        max_messages: int = 2,
        read_timeout: float = 0.2,
        max_idle_cycles: int = 5,
    ) -> None:
        super().__init__(agent_id)
        self.query = query
        self.history_path = history_path
        self.max_messages = max_messages
        self.read_timeout = read_timeout
        self.max_idle_cycles = max_idle_cycles
        self.joined = False
        self._read_pointers: list[tuple[str, int]] = []
        self._processed = 0

    def run(self, tools: SqlDemoAgentTools) -> None:
        log = tools.log.logger
        if not self.joined:
            joined = tools.channels.join_matching(self.query)
            if joined:
                log.info("joined channels", joined=joined)
                self.joined = True

        idle_cycles = 0
        while self._processed < self.max_messages:
            message = tools.messages.read(block=True, timeout=self.read_timeout)
            if message is None:
                idle_cycles += 1
                if idle_cycles >= self.max_idle_cycles:
                    break
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
                pointer = self._store_pointer(message)
                log.debug("stored pointer", channel_id=pointer[0], message_id=pointer[1])
            self._processed += 1

        self._write_history(log)
        log.info("subscriber finished", processed=self._processed)

    def _store_pointer(self, message: ChannelMessage) -> tuple[str, int]:
        pointer = (message.channel_id, message.message_id)
        self._read_pointers.append(pointer)
        return pointer

    def _write_history(self, log: Any) -> None:
        data = [
            {"channel_id": channel_id, "message_id": message_id}
            for channel_id, message_id in self._read_pointers
        ]
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text(json.dumps(data, indent=2))
        log.info("history persisted", path=str(self.history_path), count=len(data))


class PersistenceReporter(BaseDemoAgent):
    """未読キューのスナップショットを採取し、マネージャ停止を指示するエージェント。"""

    def __init__(
        self,
        agent_id: str,
        target_agent_id: str,
        *,
        wait_before_report: float = 0.5,
    ) -> None:
        super().__init__(agent_id)
        self.target_agent_id = target_agent_id
        self.wait_before_report = wait_before_report

    def run(self, tools: SqlDemoAgentTools) -> None:
        if self.wait_before_report > 0:
            time.sleep(self.wait_before_report)
        records = tools.messages.manager.snapshot_unread_records(self.target_agent_id)
        with tools.log.context(target_agent=self.target_agent_id):
            self._log_records(tools.log.logger, records)
        should_stop = callable(tools.stop_manager)
        tools.log.logger.debug("reporter stop requested", callable=should_stop)
        if should_stop:
            tools.stop_manager()
        tools.log.logger.info("reporter finished", stopped=should_stop)

    def _log_records(self, log: Any, records: Sequence[UnreadRecord]) -> None:
        log.info("snapshot captured", count=len(records))
        for record in records:
            log.debug(
                "unread record",
                channel_id=record.channel_id,
                message_id=record.message_id,
                priority=record.priority,
            )


# ---------------------------------------------------------------------------
# AgentConfig 実装
# ---------------------------------------------------------------------------


class PublisherAgentConfig(AgentConfig):
    type: Literal["sql_publisher"] = "sql_publisher"
    channel: ChannelDescriptor
    payloads: list[dict[str, Any]] = Field(default_factory=list)
    delay_before_send: float = 0.0

    def build(self) -> AlertPublisher:
        return AlertPublisher(
            agent_id=self.id,
            channel=self.channel,
            payloads=self.payloads,
            delay_before_send=self.delay_before_send,
        )


class SubscriberAgentConfig(AgentConfig):
    type: Literal["sql_subscriber"] = "sql_subscriber"
    query: ChannelSearchQuery
    history_path: Path
    max_messages: int = 2
    read_timeout: float = 0.2
    max_idle_cycles: int = 5

    def build(self) -> LimitedSubscriber:
        return LimitedSubscriber(
            agent_id=self.id,
            query=self.query,
            history_path=self.history_path,
            max_messages=self.max_messages,
            read_timeout=self.read_timeout,
            max_idle_cycles=self.max_idle_cycles,
        )


class ReporterAgentConfig(AgentConfig):
    type: Literal["sql_reporter"] = "sql_reporter"
    target_agent_id: str
    wait_before_report: float = 0.5

    def build(self) -> PersistenceReporter:
        return PersistenceReporter(
            agent_id=self.id,
            target_agent_id=self.target_agent_id,
            wait_before_report=self.wait_before_report,
        )


AGENT_TYPE_REGISTRY: dict[str, Type[AgentConfig]] = {
    "sql_publisher": PublisherAgentConfig,
    "sql_subscriber": SubscriberAgentConfig,
    "sql_reporter": ReporterAgentConfig,
}


class SqlDemoManagerConfig(StandardManagerConfig):
    config_dir: Path
    db_url: str

    def get_agent_config_paths(self) -> list[Path]:
        return sorted(self.config_dir.glob("*.json"))

    def get_agent_config_type(self, type_name: str) -> Type[AgentConfig]:
        try:
            return AGENT_TYPE_REGISTRY[type_name]
        except KeyError as exc:
            raise ValueError(f"Unknown agent type: {type_name}") from exc

    def build_tools(self) -> SqlDemoManagerTools:
        repository = SQLChannelRepository.from_url(
            self.db_url,
            connect_args={"check_same_thread": False},
        )
        channel_manager = ChannelManager(repository)
        route_provider = ChannelMessageRouteProvider(channel_manager)
        message_manager = MessageManager(repository, route_provider)
        channel_manager.attach_unread_handler(message_manager)
        return SqlDemoManagerTools(
            channel_manager=channel_manager,
            message_manager=message_manager,
        )


# ---------------------------------------------------------------------------
# 設定ファイル生成とデモ実行
# ---------------------------------------------------------------------------


def _write_config(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2))


def prepare_configs(base_dir: Path, history_path: Path) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    configs = [
        (
            "01_publisher_bootstrap.json",
            {
                "type": "sql_publisher",
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
                "type": "sql_subscriber",
                "id": "subscriber",
                "query": {"attributes": {"topic": "ops"}},
                "history_path": str(history_path),
                "max_messages": 2,
            },
        ),
        (
            "03_publisher_main.json",
            {
                "type": "sql_publisher",
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
                "delay_before_send": 0.5,
            },
        ),
        (
            "04_publisher_followup.json",
            {
                "type": "sql_publisher",
                "id": "publisher_followup",
                "channel": {
                    "name": "alerts",
                    "description": "Operations alert feed",
                    "attributes": {"topic": "ops", "level": "high"},
                },
                "payloads": [{"text": "Escalation ticket opened"}],
                "delay_before_send": 0.8,
            },
        ),
        (
            "05_reporter.json",
            {
                "type": "sql_reporter",
                "id": "reporter",
                "target_agent_id": "subscriber",
                "wait_before_report": 0.5,
            },
        ),
    ]

    for filename, data in configs:
        _write_config(base_dir / filename, data)


def replay_history_after_restart(db_url: str, history_path: Path, target_agent_id: str) -> None:
    logger.info("Replaying history with SQLChannelRepository", db_url=db_url)
    repository = SQLChannelRepository.from_url(
        db_url,
        create_tables=False,
        connect_args={"check_same_thread": False},
    )
    channel_manager = ChannelManager(repository)
    route_provider = ChannelMessageRouteProvider(channel_manager)
    message_manager = MessageManager(repository, route_provider)
    channel_manager.attach_unread_handler(message_manager)
    message_tools = MessageTools(agent_id=target_agent_id, manager=message_manager)

    unread = message_tools.read()
    if unread is not None:
        logger.info(
            "restored unread message",
            channel_id=unread.channel_id,
            message_id=unread.message_id,
            payload=unread.payload,
        )
    else:
        logger.warning("no unread message restored for agent {}", target_agent_id)

    if history_path.exists():
        pointers_raw = json.loads(history_path.read_text())
        pointers = [(item["channel_id"], int(item["message_id"])) for item in pointers_raw]
        if pointers:
            history = message_tools.fetch_messages(pointers)
            entries = [
                {
                    "channel_id": message.channel_id,
                    "message_id": message.message_id,
                    "payload": message.payload,
                }
                for message in history
            ]
            logger.info("fetched history after restart", entries=entries)
        else:
            logger.warning("history file is empty", path=str(history_path))
    else:
        logger.warning("history file not found", path=str(history_path))


def run_demo() -> None:
    state = configure_logging(enable_console=True, buffer_limit=200)
    logger.info("logging configured", state=state)
    base_dir = Path("_tmp/samples/sqlite_channels")
    config_dir = base_dir / "configs"
    history_path = base_dir / "subscriber_history.json"
    db_path = base_dir / "channels.sqlite"
    if db_path.exists():
        db_path.unlink()

    prepare_configs(config_dir, history_path)
    db_url = f"sqlite+pysqlite:///{db_path}"

    manager = StandardManager.initialize_or_load(
        config_dir,
        config_factory=lambda storage_dir: SqlDemoManagerConfig(config_dir=storage_dir, db_url=db_url),
        adapter=demo_adapter,
        execution_backend=ThreadingManagerExecutionBackend(),
    )

    tools = cast(SqlDemoManagerTools, manager.tools)
    tools.stop_manager = manager.create_stop_event_tool()

    manager.run()

    replay_history_after_restart(db_url, history_path, target_agent_id="subscriber")


if __name__ == "__main__":
    run_demo()
