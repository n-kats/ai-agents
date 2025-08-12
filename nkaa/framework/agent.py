from pathlib import Path
from typing import Type
from abc import abstractmethod, ABC
from datetime import datetime
from queue import PriorityQueue
from typing import Generator
from pydantic import BaseModel, Field


class BaseMessage(BaseModel):
    messenger_id: str
    created_at: datetime = Field(default_factory=datetime.now, description="The time when the message was created.")


class OrderedMessage:
    def __init__(self, message: BaseMessage, priority: int):
        self.__message = message
        self.__priority = priority

    def __lt__(self, other: 'OrderedMessage') -> bool:
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
        self.__queue.put(OrderedMessage(
            message=message,
            priority=self.__priorities.get(
                type(message), self.__last_priority),
            timestamp=message.created_at if hasattr(
                message, 'created_at') else datetime.now()  # TODO: created_at or received_at 問題。継承クラスのpriority問題
        ))

    def get(self) -> BaseMessage:
        return self.__queue.get().message


class BaseAgent(ABC):
    @abstractmethod
    def run(self) -> Generator[BaseMessage, None, None]:
        pass

    @abstractmethod
    def send(self, message: BaseMessage):
        pass

    @abstractmethod
    def message_types(self) -> list[Type[BaseModel]]:
        pass

class AgentConfig(BaseModel):
    def build(self, id_: str) -> BaseAgent:
        pass


class BaseChannel:
    pass


class ChannelConfig(BaseModel):
    def build(self, id_: str) -> BaseChannel:
        pass


class AgentManager:
    def __init__(self, storage_dir: Path, agent_types: list[BaseModel]):
        self.storage_dir = storage_dir
        self.agent_types = agent_types
        self.agent_type_name_to_config_class = {
            agent_type.model_fields['type'].default: agent_type
            for agent_type in agent_types
        }

    def new_id(self) -> str:
        return "agent_" + str(len(self.agents) + 1)

    def create(self, config: AgentConfig, channels_to_connect: list[str]) -> TaskAgent:
        id_ = self.new_id()
        return config.build(id_=id_)

    def find(self, id_: str) -> TaskAgent:
        # Logic# Logic to find and return a TaskAgent by its ID
        pass

    def save(self):
        # Logic# Logic to save the current state of task agents to storage
        pass

    @classmethod
    def initialize_or_load(cls, storage_dir: Path) -> 'TaskAgentManager':
        # Load existing agents from storage or initialize a new manager
        return cls()


class ChannelManager:
    def new_id(self) -> str:
        return "channel_" + str(len(self.agents) + 1)

    def create(self, config: ChannelConfig):
        return config.build(id_=self.new_id())

    def find(self, id_: str) -> BaseChannel:
        pass

    def save(self):
        pass

    @classmethod
    def initialize_or_load(cls, storage_dir: Path) -> 'ChannelManager':
        return cls()


class AgentManager:
    def __init__(
            self,
            agent_manager: AgentManager,
            channel_manager: ChannelManager,
            storage_dir: Path,
        ):
        self.agent_manager = agent_manager
        self.channel_manager = channel_manager
        self.storage_dir = storage_dir

    def create_agent(self, config: AgentConfig, channels_to_connect: list[str]):
        return self.agent_manager.create_agent(config, channels_to_connect)

    def create_channel(self, config: ChannelConfig):
        return self.channel_manager.create(config)

    def find_agent(self, agent_id: str):
        return self.agent_manager.find_agent(agent_id)

    def find_channel(self, channel_id: str):
        return self.channel_manager.find(channel_id)

    def save(self):
        self.agent_manager.save()
        self.channel_manager.save()

    @classmethod
    def initialize_or_load(self, storage_dir: Path) -> 'AgentManager':
        return AgentManager(
            agent_manager=AgentManager.initialize_or_load(
                storage_dir/"agents"),
            channel_manager=ChannelManager.initialize_or_load(
                storage_dir/"channels"),
        )

    def run(self, agents, channels):
        pass


