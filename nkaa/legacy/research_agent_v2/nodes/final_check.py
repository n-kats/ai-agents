import logging
from typing import Any

# langchain_core から直接 boolean parser をインポートするのではなく、
# langchain.output_parsers からインポートするのが一般的（バージョンによる）
# もし langchain.output_parsers.boolean が存在しない場合は、
# langchain_core.output_parsers.string など他のパーサーで代用するか、
# 依存関係を確認する必要がある
from langchain.output_parsers.boolean import BooleanOutputParser
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from nkaa.legacy.research_agent_v2.nodes.base_node import BaseNode
from nkaa.legacy.research_agent_v2.state import AgentState
from nkaa.legacy.research_agent_v2.utils.prompt_loader import load_prompt_template

# from nkaa.legacy.research_agent_v2.config.settings import Settings # DIで渡される想定

logger = logging.getLogger(__name__)

# デフォルトで使用するプロンプトテンプレート名
DEFAULT_FINAL_CHECK_PROMPT_NAME = "final_check_prompt"


class FinalCheckNode(BaseNode):
    """
    生成されたレポートの最終品質チェックを担当するノード。
    LLM を使用してレポートがクエリを満たしているか評価する。
    """

    node_name = "final_check"

    def __init__(
        self,
        llm_client: BaseChatModel,
        # settings: Settings,
        check_prompt_name: str = DEFAULT_FINAL_CHECK_PROMPT_NAME,  # 使用するプロンプト名
        **kwargs: Any,
    ):
        """
        コンストラクタ。

        Args:
            llm_client: 評価に使用するLLMクライアント。
            settings: アプリケーション設定。
            check_prompt_template: 品質チェック用のプロンプトテンプレート文字列。
        """
        super().__init__(**kwargs)
        self.llm_client = llm_client
        # self.settings = settings

        try:
            prompt_template_str = load_prompt_template(check_prompt_name)
            self.check_prompt = ChatPromptTemplate.from_template(prompt_template_str)
            logger.info(f"プロンプト '{check_prompt_name}.j2' を読み込みました。")
        except FileNotFoundError:
            logger.error(f"最終チェックプロンプトファイル '{check_prompt_name}.j2' が見つかりません。")
            self.check_prompt = ChatPromptTemplate.from_template(
                "エラー: 最終チェックプロンプトが見つかりません。クエリ: {query}"
            )
        except Exception as e:
            logger.error(
                f"最終チェックプロンプトの読み込み中にエラーが発生しました: {e}",
                exc_info=True,
            )
            self.check_prompt = ChatPromptTemplate.from_template(
                "エラー: 最終チェックプロンプト読み込みエラー。クエリ: {query}"
            )

        self.output_parser = BooleanOutputParser()

    def execute(self, state: AgentState) -> AgentState:
        """
        LLM を使用してレポートの品質をチェックし、結果を AgentState に格納する。

        Args:
            state: 現在の AgentState。

        Returns:
            チェック結果を反映した AgentState。
        """
        report = state.get("synthesis_result")
        query = state.get("current_query")  # 最新のクエリで評価

        if not report:
            # レポートがない場合はチェック失敗とするか、エラーとするか検討
            logger.warning(f"ノード '{self.node_name}': チェック対象のレポートが存在しません。")
            state["final_check_passed"] = False
            # エラーとして扱う場合:
            # return self._handle_error(state, "MissingInput", "チェック対象のレポートが state に存在しません。")
            return state
        if not query:
            return self._handle_error(state, "MissingInput", "現在のクエリが state に存在しません。")

        logger.info(f"ノード '{self.node_name}' を開始します。レポートの品質チェックを行います...")

        try:
            chain = self.check_prompt | self.llm_client | self.output_parser
            check_input = {"query": query, "report": report}
            check_result = chain.invoke(check_input)
            state["final_check_passed"] = check_result
            logger.info(f"品質チェック結果: {'合格' if check_result else '不合格'}")

        except ValueError as ve:
            # BooleanOutputParser が期待する応答を得られなかった場合
            logger.warning(f"品質チェックの評価結果を解析できませんでした: {ve}")
            state["final_check_passed"] = False  # 解析失敗時は不合格扱い
        except Exception as e:
            logger.error(f"品質チェック中に予期せぬエラーが発生しました: {e}", exc_info=True)
            # その他のエラー時もチェック失敗として扱う
            state["final_check_passed"] = False  # チェック自体は失敗
            # エラー情報を記録する
            return self._handle_error(
                state,
                error_code="CheckError",
                message=f"品質チェック中にエラーが発生しました: {e}",
                exception=e,
            )

        # チェック結果に基づいて再計画フラグを設定 (不合格なら再計画)
        state["replan_needed"] = not state["final_check_passed"]

        return state
