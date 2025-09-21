from __future__ import annotations

from typing import Callable

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from nkaa.framework.channels import ChannelManager, DatabaseChannelConfig, InMemoryChannelRepository, SQLChannelRepository
from nkaa.framework.channels.repository import ChannelRepository
from nkaa.framework.tools import ChannelTools


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


def test_channel_roundtrip_via_tools(repository_factory: RepositoryFactory) -> None:
    repository = repository_factory()
    manager = ChannelManager(repository)
    channel = manager.create(DatabaseChannelConfig(name="general"))

    tools = ChannelTools(agent_id="agent-1", manager=manager)
    tools.join(channel.id)

    stored = tools.send(channel.id, payload={"text": "hello"}, priority=1)
    assert stored.message_id is not None

    message = tools.read()
    assert message is not None
    assert message.payload == {"text": "hello"}
    assert message.priority == 1
    assert message.message_id == stored.message_id


def test_unread_queue_is_restored_from_repository(repository_factory: RepositoryFactory) -> None:
    repository = repository_factory()
    manager = ChannelManager(repository)
    channel = manager.create(DatabaseChannelConfig(name="general"))

    tools = ChannelTools(agent_id="agent-1", manager=manager)
    tools.join(channel.id)
    tools.send(channel.id, payload={"text": "persisted"})

    # Persist unread snapshot and rebuild manager from repository state.
    snapshot = tools.snapshot_unread()
    repository.replace_unread_records(snapshot)

    restored_manager = ChannelManager(repository)
    restored_message = restored_manager.read_for_agent("agent-1")

    assert restored_message is not None
    assert restored_message.payload == {"text": "persisted"}


def test_leave_channel_drops_pending_messages(repository_factory: RepositoryFactory) -> None:
    repository = repository_factory()
    manager = ChannelManager(repository)
    channel = manager.create(DatabaseChannelConfig(name="general"))

    tools = ChannelTools(agent_id="agent-1", manager=manager)
    tools.join(channel.id)
    tools.leave(channel.id)

    tools.send(channel.id, payload="ignored")
    assert tools.read() is None


def test_save_persists_agent_unread_queue(repository_factory: RepositoryFactory) -> None:
    repository = repository_factory()
    manager = ChannelManager(repository)
    channel = manager.create(DatabaseChannelConfig(name="general"))

    alice = ChannelTools(agent_id="alice", manager=manager)
    bob = ChannelTools(agent_id="bob", manager=manager)
    alice.join(channel.id)
    bob.join(channel.id)

    stored = alice.send(channel.id, payload={"text": "persist"})

    bob.save()
    assert any(record.agent_id == "bob" for record in repository.load_unread_records())

    alice.save()
    records = repository.load_unread_records()
    assert {record.agent_id for record in records} == {"alice", "bob"}

    restored_manager = ChannelManager(repository)
    alice_unread = restored_manager.read_for_agent("alice")
    bob_unread = restored_manager.read_for_agent("bob")

    assert alice_unread is not None
    assert alice_unread.message_id == stored.message_id
    assert bob_unread is not None
    assert bob_unread.message_id == stored.message_id
