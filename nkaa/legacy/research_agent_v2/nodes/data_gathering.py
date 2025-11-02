import logging
from typing import Any, Dict, List, Sequence

from nkaa.legacy.research_agent_v2.methods.base_method import BaseSearchMethod
from nkaa.legacy.research_agent_v2.nodes.base_node import BaseNode
from nkaa.legacy.research_agent_v2.state import AgentState

# from nkaa.legacy.research_agent_v2.config.settings import Settings # DIで渡される想定

logger = logging.getLogger(__name__)


class DataGatheringNode(BaseNode):
    """
    データ収集を担当するノード。
    設定に基づいて有効化された検索メソッドを実行し、結果を AgentState に集約する。
    """

    node_name = "data_gathering"

    def __init__(
        self,
        search_methods: Sequence[BaseSearchMethod],  # DI: 有効な検索メソッドのインスタンスリスト
        # settings: Settings, # DI: アプリケーション設定
        **kwargs: Any,
    ):
        """
        コンストラクタ。

        Args:
            search_methods: 実行する検索メソッドのインスタンスリスト。
            settings: アプリケーション設定。
        """
        super().__init__(**kwargs)
        self.search_methods = search_methods
        # self.settings = settings
        if not search_methods:
            logger.warning(f"ノード '{self.node_name}' に検索メソッドが指定されていません。")

    def execute(self, state: AgentState) -> AgentState:
        """
        設定された検索メソッドを実行し、結果を AgentState に格納する。

        Args:
            state: 現在の AgentState。

        Returns:
            検索結果を反映した AgentState。
        """
        query = state.get("current_query")
        if not query:
            return self._handle_error(state, "MissingInput", "検索クエリが state に存在しません。")

        if not self.search_methods:
            logger.warning(f"ノード '{self.node_name}' で実行する検索メソッドがありません。")
            state["search_results"] = []
            return state

        all_results: List[Dict[str, Any]] = []
        logger.info(f"ノード '{self.node_name}' を開始します。クエリ: '{query}'")

        for method in self.search_methods:
            method_name = method.method_name
            logger.info(f"検索メソッド '{method_name}' を実行します...")
            try:
                # ここでメソッド固有のパラメータを渡すことも可能 (settings から取得するなど)
                # 例: num_results = self.settings.get_method_param(method_name, 'num_results', 5)
                results = method(query=query)  # __call__ を利用
                logger.info(f"検索メソッド '{method_name}' が {len(results)} 件の結果を返しました。")
                # 各結果にメソッド名を付与するなど、後処理が必要な場合がある
                for res in results:
                    res["search_method"] = method_name  # どのメソッドからの結果か追跡
                all_results.extend(results)
            except Exception as e:
                logger.error(
                    f"検索メソッド '{method_name}' の実行中にエラーが発生しました: {e}",
                    exc_info=True,
                )
                # エラーが発生した場合、_handle_error を呼び出して処理を中断する
                return self._handle_error(
                    state,
                    error_code=f"{method_name.capitalize()}Error",  # 例: WebSearchError
                    message=f"検索メソッド '{method_name}' の実行に失敗しました: {e}",
                    exception=e,
                )

        logger.info(f"合計 {len(all_results)} 件の検索結果を取得しました。")
        state["search_results"] = all_results
        # データ収集後は再計画不要のはず (エラーがない限り)
        state["replan_needed"] = False

        return state
