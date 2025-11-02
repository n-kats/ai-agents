import abc

# AgentState と StructuredError をインポート (循環参照を避けるため、型チェック時のみインポート)
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from nkaa.legacy.research_agent_v2.state import AgentState
    # from nkaa.legacy.research_agent_v2.config.settings import Settings # 設定モデル (未作成)
    # from langchain_core.language_models import BaseChatModel # LLM クライアント (未作成)


class BaseNode(abc.ABC):
    """
    グラフ内の各ノード(Agent)の基底クラス。

    責務:
    - AgentState を受け取り、特定の処理を実行する。
    - 処理結果を AgentState に反映して返す。
    - 必要な依存関係 (LLMクライアント、設定など) をコンストラクタで受け取る。
    - 処理中に発生したエラーを構造化して AgentState に記録する。
    """

    node_name: str  # サブクラスで定義するノード名

    def __init__(
        self,
        # llm_client: "BaseChatModel", # DI: LLMクライアント
        # settings: "Settings",       # DI: 設定オブジェクト
        **kwargs: Any,  # 将来的な拡張用
    ):
        """
        コンストラクタ。依存性を注入する。
        """
        # self.llm_client = llm_client
        # self.settings = settings
        if not hasattr(self, "node_name") or not self.node_name:
            raise NotImplementedError("サブクラスはクラス変数 'node_name' を定義する必要があります。")

    @abc.abstractmethod
    def execute(self, state: "AgentState") -> "AgentState":
        """
        ノードの主処理を実行するメソッド。

        Args:
            state: 現在の AgentState。

        Returns:
            処理結果を反映した AgentState。
            エラー発生時は state['error_info'] に StructuredError を設定する。
        """
        raise NotImplementedError

    def _handle_error(
        self,
        state: "AgentState",
        error_code: str,
        message: str,
        details: Dict[str, Any] | None = None,
        exception: Exception | None = None,
    ) -> "AgentState":
        """
        エラー情報を AgentState に記録するヘルパーメソッド。

        Args:
            state: 現在の AgentState。
            error_code: エラーコード。
            message: エラーメッセージ。
            details: エラー詳細。
            exception: 発生した例外オブジェクト (ログ記録用など)。

        Returns:
            エラー情報を追加した AgentState。
        """
        from nkaa.legacy.research_agent_v2.state import StructuredError  # 実行時インポート

        # 例外情報をログに出力するなどの処理を追加可能
        if exception:
            # logger.error(f"Node '{self.node_name}' encountered an error: {exception}", exc_info=True)
            pass  # ロギングは別途実装

        error_info = StructuredError(
            node_name=self.node_name,
            error_code=error_code,
            message=message,
            details=details,
        )
        # TypedDict はイミュータブルではないので、直接更新可能
        state["error_info"] = error_info
        # エラー発生時は再計画フラグを立てるなどの共通処理もここで行える可能性がある
        # state["replan_needed"] = True
        return state

    def __call__(self, state: "AgentState") -> "AgentState":
        """
        クラスインスタンスを関数のように呼び出せるようにする。
        LangGraph の add_node に登録しやすくするため。
        エラーハンドリングを共通化する。
        """
        try:
            # エラー情報をクリアしてから実行
            state["error_info"] = None
            return self.execute(state)
        except Exception as e:
            # 予期せぬエラーをキャッチ
            return self._handle_error(
                state,
                error_code="UnhandledError",
                message=f"ノード '{self.node_name}' で予期せぬエラーが発生しました: {e}",
                exception=e,
            )
