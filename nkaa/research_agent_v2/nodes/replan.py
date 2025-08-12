import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from nkaa.research_agent_v2.nodes.base_node import BaseNode
from nkaa.research_agent_v2.state import AgentState
from nkaa.research_agent_v2.utils.prompt_loader import load_prompt_template

# from nkaa.research_agent_v2.config.settings import Settings # DIで渡される想定

logger = logging.getLogger(__name__)

# デフォルトで使用するプロンプトテンプレート名
DEFAULT_REPLAN_PROMPT_NAME = "replan_prompt"


class ReplanNode(BaseNode):
    """
    最終チェックで不合格だった場合に、検索クエリを再計画するノード。
    """

    node_name = "replan"

    def __init__(
        self,
        llm_client: BaseChatModel,
        # settings: Settings,
        replan_prompt_name: str = DEFAULT_REPLAN_PROMPT_NAME,  # 使用するプロンプト名
        **kwargs: Any,
    ):
        """
        コンストラクタ。

        Args:
            llm_client: 再計画に使用するLLMクライアント。
            settings: アプリケーション設定。
            replan_prompt_template: 再計画用のプロンプトテンプレート文字列。
        """
        super().__init__(**kwargs)
        self.llm_client = llm_client
        # self.settings = settings

        try:
            prompt_template_str = load_prompt_template(replan_prompt_name)
            self.replan_prompt = ChatPromptTemplate.from_template(prompt_template_str)
            logger.info(f"プロンプト '{replan_prompt_name}.j2' を読み込みました。")
        except FileNotFoundError:
            logger.error(
                f"再計画プロンプトファイル '{replan_prompt_name}.j2' が見つかりません。"
            )
            self.replan_prompt = ChatPromptTemplate.from_template(
                "エラー: 再計画プロンプトが見つかりません。初期クエリ: {initial_query}"
            )
        except Exception as e:
            logger.error(
                f"再計画プロンプトの読み込み中にエラーが発生しました: {e}",
                exc_info=True,
            )
            self.replan_prompt = ChatPromptTemplate.from_template(
                "エラー: 再計画プロンプト読み込みエラー。初期クエリ: {initial_query}"
            )

        self.output_parser = StrOutputParser()

    def execute(self, state: AgentState) -> AgentState:
        """
        LLM を使用して新しい検索クエリを生成し、AgentState を更新する。

        Args:
            state: 現在の AgentState。

        Returns:
            再計画されたクエリとリセットされた状態を持つ AgentState。
        """
        initial_query = state.get("initial_query")
        current_query = state.get("current_query")
        report = state.get(
            "synthesis_result", "(レポートなし)"
        )  # レポートがない場合も考慮

        if not initial_query:
            return self._handle_error(
                state, "MissingInput", "初期クエリが state に存在しません。"
            )
        if not current_query:
            # current_query がない場合は initial_query を使う
            current_query = initial_query
            logger.warning(
                "current_query が見つからないため、initial_query を使用します。"
            )

        # 再計画が必要かどうかのチェック (グラフの条件分岐で制御されるはずだが念のため)
        if not state.get("replan_needed", False):
            logger.info(
                f"ノード '{self.node_name}': 再計画は不要と判断されました。スキップします。"
            )
            # replan_needed が False の場合、何もせず state を返すか、エラーにするか検討
            # ここでは何もせず返す
            return state

        # 再計画回数をインクリメント
        current_attempts = state.get("replan_attempts", 0)
        state["replan_attempts"] = current_attempts + 1
        logger.info(f"再計画試行回数: {state['replan_attempts']}")

        logger.info(
            f"ノード '{self.node_name}' を開始します。検索クエリの再計画を行います..."
        )

        try:
            chain = self.replan_prompt | self.llm_client | self.output_parser
            replan_input = {
                "initial_query": initial_query,
                "current_query": current_query,
                "report": report,
            }
            new_query = chain.invoke(replan_input).strip()

            if not new_query:
                logger.warning(
                    "LLMが新しいクエリを生成できませんでした。元のクエリを維持します。"
                )
                # 新しいクエリが空の場合、エラーにするか、元のクエリを維持するか選択
                # ここでは元のクエリを維持し、エラーとはしない
                state["replan_needed"] = False  # 再計画試行はしたので False にする
                return state

            logger.info(f"新しい検索クエリが生成されました: '{new_query}'")
            state["current_query"] = new_query

            # 次のサイクルに向けて関連状態をリセット
            state["search_plan"] = None  # 検索プランもリセット/再生成が必要な場合
            state["search_results"] = []
            state["analysis_results"] = {}
            state["synthesis_result"] = None
            state["final_check_passed"] = None
            state["error_info"] = None  # 前回の実行エラーはクリア

            # 再計画が実行されたのでフラグを False に戻す
            state["replan_needed"] = False

        except Exception as e:
            logger.error(f"再計画中にエラーが発生しました: {e}", exc_info=True)
            # エラー発生時は再計画失敗とし、ループを止めるために replan_needed を False にする
            state["replan_needed"] = False
            # エラー情報を記録
            return self._handle_error(
                state,
                "ReplanError",
                f"再計画中にエラーが発生しました: {e}",
                exception=e,
            )

        return state
