from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from queue import Empty, PriorityQueue
from typing import Type

from pydantic import BaseModel, Field


class BaseChannel(ABC):
    """チャネルの基本インターフェース。"""

    def __init__(self, id_: str, *, queue: "MessageQueue | None" = None) -> None:
        self.id = id_
        self._queue = queue or MessageQueue()

    @abstractmethod
    def write(self, message: "BaseMessage") -> None:
        """チャネルにメッセージを書き込む。"""
        raise NotImplementedError

    @abstractmethod
    def read(self) -> "BaseMessage | None":
        """チャネルから次のメッセージを取得する。"""
        raise NotImplementedError

    def save(self) -> None:
        """必要に応じてチャネルの状態を永続化するフック。"""
        # デフォルト実装では何もしない。
        return None


class InMemoryChannel(BaseChannel):
    """優先度付きキューを利用した単純なインメモリチャネル実装。"""

    def write(self, message: "BaseMessage") -> None:
        self._queue.put(message)

    def read(self) -> "BaseMessage | None":
        return self._queue.get()


class ChannelConfig(BaseModel):
    def build(self, id_: str) -> BaseChannel:
        raise NotImplementedError("ChannelConfig.build must be implemented by subclasses")


class InMemoryChannelConfig(ChannelConfig):
    """デフォルトのインメモリチャネル設定。"""

    def build(self, id_: str) -> BaseChannel:
        return InMemoryChannel(id_)


class ChannelManager:
    def __init__(self, storage_dir: Path | None = None) -> None:
        self.storage_dir = storage_dir
        self.channels: dict[str, BaseChannel] = {}
        self._next_index = 1

    def new_id(self) -> str:
        next_id = f"channel_{self._next_index}"
        self._next_index += 1
        return next_id

    def register(self, channel: BaseChannel) -> BaseChannel:
        self.channels[channel.id] = channel
        self._next_index = max(self._next_index, self._extract_counter(channel.id) + 1)
        return channel

    def create(self, config: ChannelConfig) -> BaseChannel:
        channel = config.build(id_=self.new_id())
        return self.register(channel)

    def find(self, id_: str) -> BaseChannel:
        try:
            return self.channels[id_]
        except KeyError as exc:
            raise KeyError(f"Channel '{id_}' not found") from exc

    def save(self) -> None:
        for channel in self.channels.values():
            channel.save()

    @classmethod
    def initialize_or_load(cls, storage_dir: Path) -> "ChannelManager":
        # 永続化形式が未整備のため、現状は新規初期化のみを行う。
        return cls(storage_dir=storage_dir)

    @staticmethod
    def _extract_counter(channel_id: str) -> int:
        prefix = "channel_"
        if channel_id.startswith(prefix):
            suffix = channel_id[len(prefix) :]
            if suffix.isdigit():
                return int(suffix)
        return 0


class BaseMessage(BaseModel):
    messenger_id: str
    created_at: datetime = Field(default_factory=datetime.now, description="The time when the message was created.")


class OrderedMessage:
    def __init__(self, message: BaseMessage, priority: int):
        self.__message = message
        self.__priority = priority

    def __lt__(self, other: "OrderedMessage") -> bool:
        if self.__priority != other.__priority:
            return self.__priority < other.__priority
        return self.message.created_at < other.message.created_at

    @property
    def message(self) -> BaseMessage:
        return self.__message


class MessageQueue:
    def __init__(self, priorities: dict[Type[BaseMessage], int] = None):
        self.__queue = PriorityQueue()
        self.__priorities = priorities.copy() if priorities is not None else {}
        self.__last_priority = max(self.__priorities.values(), default=0) + 1

    def put(self, message: BaseMessage):
        self.__queue.put(
            OrderedMessage(
                message=message,
                priority=self.__priorities.get(type(message), self.__last_priority),
            )
        )

    def get(self, block: bool = False, timeout: float | None = None) -> BaseMessage | None:
        try:
            ordered = self.__queue.get(block=block, timeout=timeout)
        except Empty:
            return None
        return ordered.message

    def empty(self) -> bool:
        return self.__queue.empty()
