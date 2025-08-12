import abc
from typing import Any, Dict, List

# AgentState をインポート (将来的にメソッドが State 全体を参照する必要がある場合に備える)
# from typing import TYPE_CHECKING
# if TYPE_CHECKING:
#     from nkaa.research_agent_v2.state import AgentState


class BaseSearchMethod(abc.ABC):
    """
    検索メソッドの基底クラス。

    責務:
    - 特定の検索方法（Web検索、ローカルファイル検索など）を実装する。
    - 検索クエリやパラメータを受け取り、検索結果のリストを返す。
    """

    method_name: str  # サブクラスで定義するメソッド名

    def __init__(self, **kwargs: Any):
        """
        コンストラクタ。必要に応じてAPIキーなどの設定を受け取る。
        """
        if not hasattr(self, "method_name") or not self.method_name:
            raise NotImplementedError(
                "サブクラスはクラス変数 'method_name' を定義する必要があります。"
            )
        # 設定の初期化など

    @abc.abstractmethod
    def execute(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
        """
        検索を実行するメソッド。

        Args:
            query: 検索クエリ文字列。
            **kwargs: メソッド固有の追加パラメータ (例: num_results, file_types)。

        Returns:
            検索結果のリスト。各要素は以下のような辞書形式を想定:
            - Web検索の場合: {"source": "web", "url": "...", "title": "...", "snippet": "...", "content": "..."}
            - ローカル検索の場合: {"source": "local", "path": "...", "content": "...", "metadata": {...}}
            ※ content は取得できた場合のみ。取得できない場合は None や空文字。
        """
        raise NotImplementedError

    def __call__(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
        """クラスインスタンスを関数のように呼び出せるようにする。"""
        return self.execute(query, **kwargs)


class BaseAnalysisMethod(abc.ABC):
    """
    分析メソッドの基底クラス。

    責務:
    - 特定の分析方法（要約、キーワード抽出など）を実装する。
    - 分析対象のデータを受け取り、分析結果を返す。
    """

    method_name: str  # サブクラスで定義するメソッド名

    def __init__(
        self,
        # llm_client: "BaseChatModel", # DI: LLMクライアント (必要な場合)
        # settings: "Settings",       # DI: 設定オブジェクト (必要な場合)
        **kwargs: Any,
    ):
        """
        コンストラクタ。必要に応じてLLMクライアントや設定を受け取る。
        """
        if not hasattr(self, "method_name") or not self.method_name:
            raise NotImplementedError(
                "サブクラスはクラス変数 'method_name' を定義する必要があります。"
            )
        # self.llm_client = llm_client
        # self.settings = settings
        # その他の初期化

    @abc.abstractmethod
    def execute(self, data: Any, **kwargs: Any) -> Any:
        """
        分析を実行するメソッド。

        Args:
            data: 分析対象のデータ (例: テキスト文字列、文書リスト)。
            **kwargs: メソッド固有の追加パラメータ。

        Returns:
            分析結果 (例: 要約文字列、キーワードリスト)。型はメソッドによる。
        """
        raise NotImplementedError

    def __call__(self, data: Any, **kwargs: Any) -> Any:
        """クラスインスタンスを関数のように呼び出せるようにする。"""
        return self.execute(data, **kwargs)


# Protocol を使う選択肢もある (より柔軟だが、実装強制力は ABC より弱い)
# class SearchMethodCallable(Protocol):
#     def __call__(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]: ...

# class AnalysisMethodCallable(Protocol):
#     def __call__(self, data: Any, **kwargs: Any) -> Any: ...
