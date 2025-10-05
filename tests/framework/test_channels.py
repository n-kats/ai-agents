from __future__ import annotations

import asyncio
from typing import Callable

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from nkaa.framework.channels import (
    ChannelManager,
    ChannelSearchQuery,
    DatabaseChannelConfig,
    InMemoryChannelRepository,
    SQLChannelRepository,
)
from nkaa.framework.channels.message_routing import ChannelMessageRouteProvider
from nkaa.framework.channels.models import ChannelMessage
from nkaa.framework.channels.repository import ChannelRepository
from nkaa.framework.message_manager import MessageManager
from nkaa.framework.tools import ChannelTools, MessageTools


def _sqlite_repository_factory() -> SQLChannelRepository:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return SQLChannelRepository(engine)


RepositoryFactory = Callable[[], ChannelRepository]


@pytest.fixture(params=[InMemoryChannelRepository, _sqlite_repository_factory], ids=["memory", "sqlite"])
def repository_factory(request: pytest.FixtureRequest) -> RepositoryFactory:
    factory: RepositoryFactory = request.param
    return factory


def _build_managers(repository: ChannelRepository) -> tuple[ChannelManager, MessageManager]:
    channel_manager = ChannelManager(repository)
    route_provider = ChannelMessageRouteProvider(channel_manager)
    message_manager = MessageManager(repository, route_provider)
    channel_manager.attach_unread_handler(message_manager)
    return channel_manager, message_manager


def test_channel_roundtrip_via_tools(repository_factory: RepositoryFactory) -> None:
    repository = repository_factory()
    channel_manager, message_manager = _build_managers(repository)
    channel = channel_manager.create(DatabaseChannelConfig(name="general"))

    channels = ChannelTools(agent_id="agent-1", manager=channel_manager)
    messages = MessageTools(agent_id="agent-1", manager=message_manager)
    channels.join(channel.id)

    stored = messages.send(channel.id, payload={"text": "hello"}, priority=1)
    assert stored.message_id is not None

    message = messages.read()
    assert message is not None
    assert message.payload == {"text": "hello"}
    assert message.priority == 1
    assert message.message_id == stored.message_id


def test_unread_queue_is_restored_from_repository(repository_factory: RepositoryFactory) -> None:
    repository = repository_factory()
    channel_manager, message_manager = _build_managers(repository)
    channel = channel_manager.create(DatabaseChannelConfig(name="general"))

    channels = ChannelTools(agent_id="agent-1", manager=channel_manager)
    messages = MessageTools(agent_id="agent-1", manager=message_manager)
    channels.join(channel.id)
    messages.send(channel.id, payload={"text": "persisted"})

    # Persist unread snapshot and rebuild manager from repository state.
    snapshot = messages.snapshot_unread()
    repository.replace_unread_records(snapshot)

    restored_channel_manager, restored_message_manager = _build_managers(repository)
    restored_message = restored_message_manager.read_for_agent("agent-1")

    assert restored_message is not None
    assert restored_message.payload == {"text": "persisted"}


def test_leave_channel_drops_pending_messages(repository_factory: RepositoryFactory) -> None:
    repository = repository_factory()
    channel_manager, message_manager = _build_managers(repository)
    channel = channel_manager.create(DatabaseChannelConfig(name="general"))

    channels = ChannelTools(agent_id="agent-1", manager=channel_manager)
    messages = MessageTools(agent_id="agent-1", manager=message_manager)
    channels.join(channel.id)
    channels.leave(channel.id)

    messages.send(channel.id, payload="ignored")
    assert messages.read() is None


def test_save_persists_agent_unread_queue(repository_factory: RepositoryFactory) -> None:
    repository = repository_factory()
    channel_manager, message_manager = _build_managers(repository)
    channel = channel_manager.create(DatabaseChannelConfig(name="general"))

    alice_channels = ChannelTools(agent_id="alice", manager=channel_manager)
    bob_channels = ChannelTools(agent_id="bob", manager=channel_manager)
    alice_messages = MessageTools(agent_id="alice", manager=message_manager)
    bob_messages = MessageTools(agent_id="bob", manager=message_manager)
    alice_channels.join(channel.id)
    bob_channels.join(channel.id)

    stored = alice_messages.send(channel.id, payload={"text": "persist"})

    bob_messages.save()
    assert any(record.agent_id == "bob" for record in repository.load_unread_records())

    alice_messages.save()
    records = repository.load_unread_records()
    assert {record.agent_id for record in records} == {"alice", "bob"}

    restored_channel_manager, restored_message_manager = _build_managers(repository)
    alice_unread = restored_message_manager.read_for_agent("alice")
    bob_unread = restored_message_manager.read_for_agent("bob")

    assert alice_unread is not None
    assert alice_unread.message_id == stored.message_id
    assert bob_unread is not None
    assert bob_unread.message_id == stored.message_id


def test_channel_search_and_auto_join(repository_factory: RepositoryFactory) -> None:
    repository = repository_factory()
    channel_manager, message_manager = _build_managers(repository)
    general = channel_manager.create(DatabaseChannelConfig(name="general", attributes={"topic": "general"}))
    alerts = channel_manager.create(
        DatabaseChannelConfig(name="alerts", description="operations", attributes={"topic": "ops", "level": "high"})
    )
    random = channel_manager.create(DatabaseChannelConfig(name="random", description="Chit chat"))

    tools = ChannelTools(agent_id="agent-2", manager=channel_manager)

    all_channels = tools.search()
    assert {metadata.id for metadata in all_channels} == {general.id, alerts.id, random.id}

    name_query = ChannelSearchQuery(name_contains="alert")
    matched = tools.search(name_query)
    assert [metadata.id for metadata in matched] == [alerts.id]

    attribute_query = ChannelSearchQuery(attributes={"topic": "ops"})
    joined = tools.join_matching(attribute_query)
    assert joined == (alerts.id,)
    assert alerts.id in tools.joined_channels()

    # 再度 join_matching を呼んでも既存参加チャネルは重複しない
    again = tools.join_matching(attribute_query)
    assert again == ()


def test_channel_tools_async_send_and_read(repository_factory: RepositoryFactory) -> None:
    repository = repository_factory()
    if not isinstance(repository, InMemoryChannelRepository):
        pytest.skip("Async channel smoke test is limited to in-memory repository for now")
    channel_manager, message_manager = _build_managers(repository)
    channel = channel_manager.create(DatabaseChannelConfig(name="async"))

    sender_channels = ChannelTools(agent_id="sender", manager=channel_manager)
    receiver_channels = ChannelTools(agent_id="receiver", manager=channel_manager)
    sender_messages = MessageTools(agent_id="sender", manager=message_manager)
    receiver_messages = MessageTools(agent_id="receiver", manager=message_manager)
    sender_channels.join(channel.id)
    receiver_channels.join(channel.id)

    async def scenario() -> None:
        stored = await sender_messages.send_async(channel.id, payload={"text": "async hello"})
        assert stored.message_id is not None
        message = await receiver_messages.read_async(poll_interval=0.05)
        assert isinstance(message, ChannelMessage)
        assert message.message_id == stored.message_id
        assert message.payload == {"text": "async hello"}

    asyncio.run(scenario())
