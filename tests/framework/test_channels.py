from __future__ import annotations

from nkaa.framework.channels import (
    ChannelManager,
    DatabaseChannelConfig,
    InMemoryChannelRepository,
)
from nkaa.framework.tools import ChannelTools


def test_channel_roundtrip_via_tools() -> None:
    repository = InMemoryChannelRepository()
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


def test_unread_queue_is_restored_from_repository() -> None:
    repository = InMemoryChannelRepository()
    manager = ChannelManager(repository)
    channel = manager.create(DatabaseChannelConfig(name="general"))

    tools = ChannelTools(agent_id="agent-1", manager=manager)
    tools.join(channel.id)
    tools.send(channel.id, payload={"text": "persisted"})

    # Persist unread snapshot and rebuild manager from repository state.
    manager.save()

    restored_manager = ChannelManager(repository)
    restored_message = restored_manager.read_for_agent("agent-1")

    assert restored_message is not None
    assert restored_message.payload == {"text": "persisted"}


def test_leave_channel_drops_pending_messages() -> None:
    repository = InMemoryChannelRepository()
    manager = ChannelManager(repository)
    channel = manager.create(DatabaseChannelConfig(name="general"))

    tools = ChannelTools(agent_id="agent-1", manager=manager)
    tools.join(channel.id)
    tools.leave(channel.id)

    tools.send(channel.id, payload="ignored")
    assert tools.read() is None
