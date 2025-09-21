import json
from abc import ABC, abstractmethod
from multiprocessing import Event, Process
from pathlib import Path
from typing import Callable, Generic, Type, TypeVar, cast

from pydantic import BaseModel


class BaseTools(ABC):
    @abstractmethod
    def stop(self) -> None:
        """
        ツールの実行を停止するメソッド。
        """
        pass

    @abstractmethod
    def save(self) -> None:
        """
        ツールの状態を保存するメソッド。
        """
        pass


TTools = TypeVar("TTools", bound=BaseTools)


class BaseAgent(ABC, Generic[TTools]):
    @abstractmethod
    def run(self, tools: TTools) -> None:
        """
        エージェントのメインロジックを実行するメソッド。
        Args:
            tools (TTools): エージェントが使用するツールのインスタンス。
                ツールを介してLLMの実行、他エージェントとの通信、ログの記録などを行う。
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """
        エージェントの実行を停止するメソッド。
        """
        pass

    @abstractmethod
    def load(self) -> None:
        """
        エージェントの状態をロードするメソッド。
        """
        pass

    @abstractmethod
    def save(self) -> None:
        """
        エージェントの状態を保存するメソッド。
        """
        pass


class AgentConfig(BaseModel):
    type: str
    id: str

    def build(self) -> BaseAgent:
        """Instantiate the concrete agent defined by this configuration."""
        raise NotImplementedError("AgentConfig.build must be implemented by subclasses")


class BaseManager(ABC):
    @abstractmethod
    def run(self) -> None:
        """
        マネージャーのメインロジックを実行するメソッド。
        Args:
            tools (TManagerTools): マネージャーが使用するツールのインスタンス。
                ツールを介してLLMの実行、他エージェントとの通信、ログの記録などを行う。
        """
        pass

    @abstractmethod
    def save(self) -> None:
        """
        マネージャーとその管理下にあるすべてのものを保存するメソッド。
        """
        pass

    @classmethod
    @abstractmethod
    def initialize_or_load(cls, storage_dir: Path) -> "BaseManager":
        """
        ストレージディレクトリからマネージャーを初期化またはロードするクラスメソッド。
        Args:
            storage_dir (Path): ストレージディレクトリのパス。
        Returns:
            BaseManager: 初期化またはロードされたマネージャーのインスタンス。
        """
        pass


class StandardManagerConfig(ABC, BaseModel):
    @abstractmethod
    def get_agent_config_paths(self) -> list[Path]:
        """
        マネージャーが管理するエージェントの設定ファイルのパスを返すメソッド。
        Returns:
            list[AgentConfig]: エージェントの設定ファイルのパスのリスト。
        """

    @abstractmethod
    def get_agent_config_type(self, type_name: str) -> Type[AgentConfig]:
        """
        エージェントの設定モデルタイプを取得するメソッド。
        Args:
            type_name (str): エージェントのタイプ名。
        Returns:
            Type[AgentConfig]: 指定されたタイプ名に対応する設定モデルのクラス。
        """


TManagerConfig = TypeVar("TManagerConfig", bound=StandardManagerConfig)
TManagerTools = TypeVar("TManagerTools", bound=BaseTools)


class StandardManager(BaseManager, Generic[TManagerConfig, TManagerTools, TTools]):
    def __init__(
        self,
        config: TManagerConfig,
        adapter: Callable[[BaseAgent[TTools], TManagerTools], TTools],
    ) -> None:
        """
        Args:
            config (TManagerConfig): マネージャーの設定。
            adapter (Callable[[BaseAgent[TTools], TManagerTools], TTools]):
                エージェントにツールを適用するためのアダプター関数。
        """
        self.config = config
        self.agents: list[BaseAgent[TTools]] = [
            self._load_agent(config_path) for config_path in config.get_agent_config_paths()
        ]
        self.adapter = adapter

        self.tools: TManagerTools = self._load_tools()
        self.agent_processes: list[Process] = []
        self.stop_event = Event()

    def _load_agent(self, config_path: Path) -> BaseAgent[TTools]:
        """
        指定された設定ファイルからエージェントをロードするメソッド。
        Args:
            config_path (Path): エージェントの設定ファイルのパス。
        Returns:
            BaseAgent[TTools]: ロードされたエージェントのインスタンス。
        """
        raw_text = config_path.read_text()
        data = json.loads(raw_text)
        agent_config_type = self.config.get_agent_config_type(data["type"])
        agent_config = agent_config_type.model_validate_json(raw_text)
        agent = cast(BaseAgent[TTools], agent_config.build())
        agent.load()
        return agent

    def apply_adapter(self, agent: BaseAgent[TTools]) -> TTools:
        """
        エージェントにツールを適用するためのアダプターを適用するメソッド。
        """
        return self.adapter(agent, self.tools)

    def run(self) -> None:
        """
        標準マネージャーのメインロジックを実行するメソッド。
        """
        assert self.agent_processes == [], "Manager is already running."
        self.agent_processes = [Process(target=agent.run, args=(self.apply_adapter(agent),)) for agent in self.agents]
        for process in self.agent_processes:
            print(f"Starting agent process: {process}")
            process.start()

        self.stop_event.wait()
        self.tools.stop()
        for agent in self.agents:
            agent.stop()

        self.save()

    def save(self) -> None:
        """
        標準マネージャーとその管理下にあるすべてのものを保存するメソッド。
        """
        for agent in self.agents:
            agent.save()

    @abstractmethod
    def _load_tools(self) -> TManagerTools:
        """
        マネージャーが使用するツールをロードするメソッド。
        設定はconfigから取得され、ツールのインスタンスが返されます。
        Returns:
            TManagerTools: ロードされたツールのインスタンス。
        """
        pass

    def create_stop_event_tool(self) -> Callable[[], None]:
        """
        エージェントの実行を停止するためのイベントツールを作成するメソッド。
        Returns:
            Event: エージェントの実行を停止するためのイベント。
        """
        return self.stop_event.set
