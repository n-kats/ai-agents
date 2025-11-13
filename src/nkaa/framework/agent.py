import asyncio
import inspect
import json
import multiprocessing
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Generic, Protocol, Type, TypeVar, cast

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


TSpecificAgent = TypeVar("TSpecificAgent", bound="BaseAgent[Any]")


class AgentConfig(BaseModel):
    type: str
    id: str

    def build(self) -> BaseAgent:
        """この設定で定義された具体的なエージェントを生成する。"""
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

    @abstractmethod
    def build_tools(self) -> BaseTools:
        """この設定に紐づくツールセットを構築する。"""


TManagerConfig = TypeVar("TManagerConfig", bound=StandardManagerConfig)
TManagerTools = TypeVar("TManagerTools", bound=BaseTools)


class _StopEvent(Protocol):
    def wait(self, timeout: float | None = None) -> bool: ...

    def set(self) -> None: ...


class _WorkerHandle(Protocol):
    def start(self) -> None: ...

    def join(self, timeout: float | None = None) -> None: ...

    def is_alive(self) -> bool: ...


def _run_agent_worker(agent: "BaseAgent[Any]", tools: BaseTools) -> None:
    """エージェントが提供する非同期エントリーポイントを優先して実行する。"""

    run_async = getattr(agent, "run_async", None)
    if run_async is not None and inspect.iscoroutinefunction(run_async):
        coroutine = run_async(tools)  # type: ignore[misc]
        asyncio.run(coroutine)
        return
    agent.run(tools)


class ManagerExecutionBackend(Protocol):
    def create_event(self) -> _StopEvent:
        """停止制御用イベントを生成する。"""

        ...

    def create_worker(self, target: Callable[..., None], args: tuple[Any, ...]) -> _WorkerHandle:
        """エージェント実行ハンドルを生成する。"""

        ...


class MultiprocessingManagerExecutionBackend:
    """multiprocessing を利用して各エージェントを別プロセスで実行するバックエンド。"""

    def create_event(self) -> _StopEvent:
        return multiprocessing.Event()

    def create_worker(self, target: Callable[..., None], args: tuple[Any, ...]) -> _WorkerHandle:
        return multiprocessing.Process(target=target, args=args)


class ThreadingManagerExecutionBackend:
    """threading を利用して各エージェントをスレッドで実行するバックエンド。"""

    def __init__(self, *, daemon: bool = True) -> None:
        self.daemon = daemon

    def create_event(self) -> _StopEvent:
        return threading.Event()

    def create_worker(self, target: Callable[..., None], args: tuple[Any, ...]) -> _WorkerHandle:
        return threading.Thread(target=target, args=args, daemon=self.daemon)


class StandardManager(BaseManager, Generic[TManagerConfig, TManagerTools, TTools]):
    def __init__(
        self,
        config: TManagerConfig,
        adapter: Callable[[BaseAgent[TTools], TManagerTools], TTools],
        *,
        tools: TManagerTools,
        execution_backend: ManagerExecutionBackend | None = None,
    ) -> None:
        """
        Args:
            config (TManagerConfig): マネージャーの設定。
            adapter (Callable[[BaseAgent[TTools], TManagerTools], TTools]):
                エージェントにツールを適用するためのアダプター関数。
        """
        self.config = config
        self._agents_by_id: dict[str, BaseAgent[TTools]] = {}
        self.agents: list[BaseAgent[TTools]] = []
        for config_path in config.get_agent_config_paths():
            agent_id, agent = self._load_agent(config_path)
            if agent_id in self._agents_by_id:
                raise ValueError(f"Duplicate agent id detected: {agent_id}")
            self.agents.append(agent)
            self._agents_by_id[agent_id] = agent
        self.adapter = adapter
        self.execution_backend = execution_backend or MultiprocessingManagerExecutionBackend()
        self.stop_event = self.execution_backend.create_event()

        self.tools = tools
        self.agent_processes: list[_WorkerHandle] = []

    def _load_agent(self, config_path: Path) -> tuple[str, BaseAgent[TTools]]:
        """
        指定された設定ファイルからエージェントをロードするメソッド。
        Args:
            config_path (Path): エージェントの設定ファイルのパス。
        Returns:
            tuple[str, BaseAgent[TTools]]: エージェントIDとインスタンス。
        """
        raw_text = config_path.read_text()
        data = json.loads(raw_text)
        agent_config_type = self.config.get_agent_config_type(data["type"])
        agent_config = agent_config_type.model_validate_json(raw_text)
        agent = cast(BaseAgent[TTools], agent_config.build())
        configured_agent_id = agent_config.id
        runtime_agent_id = getattr(agent, "agent_id", configured_agent_id)
        if runtime_agent_id != configured_agent_id:
            raise ValueError(
                "Agent ID mismatch: config specifies '{config}', but agent exposes '{runtime}'.".format(
                    config=configured_agent_id,
                    runtime=runtime_agent_id,
                )
            )
        agent.load()
        return configured_agent_id, agent

    def get_agent(
        self,
        agent_id: str,
        *,
        expected_type: type[TSpecificAgent] | None = None,
    ) -> BaseAgent[TTools] | TSpecificAgent:
        """ID でエージェントを取得するヘルパー。"""

        try:
            agent = self._agents_by_id[agent_id]
        except KeyError as exc:  # pragma: no cover - defensive path
            raise KeyError(f"Agent with id '{agent_id}' is not registered.") from exc

        if expected_type is not None:
            if not isinstance(agent, expected_type):
                raise TypeError(
                    "Agent '{agent_id}' is of type '{actual}' (expected '{expected}').".format(
                        agent_id=agent_id,
                        actual=type(agent).__name__,
                        expected=expected_type.__name__,
                    )
                )
            return cast(TSpecificAgent, agent)
        return agent

    def apply_adapter(self, agent: BaseAgent[TTools]) -> TTools:
        """
        エージェントにツールを適用するためのアダプターを適用するメソッド。
        """
        return self.adapter(agent, self.tools)

    def run(self) -> None:
        asyncio.run(self.run_async())

    async def run_async(self) -> None:
        """標準マネージャーを非同期コンテキストで実行する。"""

        assert self.agent_processes == [], "Manager is already running."
        agent_contexts: list[tuple[BaseAgent[TTools], TTools]] = [
            (agent, self.apply_adapter(agent)) for agent in self.agents
        ]

        self.agent_processes = [
            self.execution_backend.create_worker(
                target=_run_agent_worker,
                args=(agent, tools),
            )
            for agent, tools in agent_contexts
        ]
        for process in self.agent_processes:
            print(f"Starting agent process: {process}")
            process.start()

        try:
            await asyncio.to_thread(self.stop_event.wait)
        finally:
            await asyncio.to_thread(self.tools.stop)
            for agent in self.agents:
                agent.stop()

            await asyncio.gather(
                *(asyncio.to_thread(process.join) for process in self.agent_processes),
                return_exceptions=True,
            )
            await asyncio.to_thread(self.save)
            self.agent_processes = []

    def save(self) -> None:
        """
        標準マネージャーとその管理下にあるすべてのものを保存するメソッド。
        """
        self.tools.save()
        for agent in self.agents:
            agent.save()

    def create_stop_event_tool(self) -> Callable[[], None]:
        """
        エージェントの実行を停止するためのイベントツールを作成するメソッド。
        Returns:
            Event: エージェントの実行を停止するためのイベント。
        """
        return self.stop_event.set

    @classmethod
    def initialize_or_load(
        cls,
        storage_dir: Path,
        *,
        config_factory: Callable[[Path], TManagerConfig] | None = None,
        adapter: Callable[[BaseAgent[TTools], TManagerTools], TTools] | None = None,
        tools_factory: Callable[[TManagerConfig], TManagerTools] | None = None,
        execution_backend: ManagerExecutionBackend | None = None,
    ) -> "StandardManager[TManagerConfig, TManagerTools, TTools]":
        if config_factory is None:
            raise ValueError("config_factory must be provided")
        if adapter is None:
            raise ValueError("adapter must be provided")

        config = config_factory(storage_dir)
        tools = tools_factory(config) if tools_factory is not None else cast(TManagerTools, config.build_tools())

        return cls(
            config,
            adapter,
            tools=tools,
            execution_backend=execution_backend,
        )
