import logging
from typing import Any, Dict, List, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from nkaa.research_agent_v2.methods.base_method import BaseAnalysisMethod
from nkaa.research_agent_v2.nodes.base_node import BaseNode
from nkaa.research_agent_v2.state import AgentState
from nkaa.research_agent_v2.utils.prompt_loader import load_prompt_template

# from nkaa.research_agent_v2.config.settings import Settings # DIで渡される想定

logger = logging.getLogger(__name__)

# デフォルトで使用するプロンプトテンプレート名
DEFAULT_SYNTHESIS_PROMPT_NAME = "synthesis_prompt"


class AnalysisSynthesisNode(BaseNode):
    """
    検索結果の分析と統合レポート生成を担当するノード。
    """

    node_name = "analysis_synthesis"

    def __init__(
        self,
        analysis_methods: Sequence[BaseAnalysisMethod],
        llm_client: BaseChatModel,
        # settings: Settings,
        synthesis_prompt_name: str = DEFAULT_SYNTHESIS_PROMPT_NAME,  # 使用するプロンプト名
        **kwargs: Any,
    ):
        """
        コンストラクタ。

        Args:
            analysis_methods: 実行する分析メソッドのインスタンスリスト。
            llm_client: レポート合成に使用するLLMクライアント。
            settings: アプリケーション設定。
            synthesis_prompt_template: レポート合成用のプロンプトテンプレート文字列。
        """
        super().__init__(**kwargs)
        self.analysis_methods = analysis_methods
        self.llm_client = llm_client
        # self.settings = settings

        try:
            # プロンプトテンプレートをファイルから読み込む
            prompt_template_str = load_prompt_template(synthesis_prompt_name)
            self.synthesis_prompt = ChatPromptTemplate.from_template(prompt_template_str)
            logger.info(f"プロンプト '{synthesis_prompt_name}.j2' を読み込みました。")
        except FileNotFoundError:
            logger.error(
                f"合成プロンプトファイル '{synthesis_prompt_name}.j2' が見つかりません。デフォルトのプロンプト構造を使用します（機能しない可能性があります）。"
            )
            # フォールバックとして空のテンプレートやエラーを示すテンプレートを設定することも検討
            self.synthesis_prompt = ChatPromptTemplate.from_template(
                "エラー: 合成プロンプトテンプレートが見つかりません。クエリ: {query}"
            )
        except Exception as e:
            logger.error(
                f"合成プロンプトの読み込み中に予期せぬエラーが発生しました: {e}",
                exc_info=True,
            )
            # 同様にフォールバック
            self.synthesis_prompt = ChatPromptTemplate.from_template(
                "エラー: 合成プロンプトの読み込みエラー。クエリ: {query}"
            )

        self.output_parser = StrOutputParser()

        if not analysis_methods:
            logger.warning(f"ノード '{self.node_name}' に分析メソッドが指定されていません。")

    def _format_search_results_summary(self, search_results: List[Dict[str, Any]], max_items: int = 5) -> str:
        """検索結果を要約してプロンプトに含めるためのヘルパー"""
        if not search_results:
            return "検索結果なし"
        summary = []
        for i, res in enumerate(search_results[:max_items]):
            source = res.get("source", "不明")
            title = res.get("title", res.get("path", "タイトル不明"))
            snippet = res.get("snippet", res.get("content", "")[:100])  # スニペットかコンテンツの先頭
            summary.append(f"{i + 1}. [{source}] {title}\n   {snippet}...")
        if len(search_results) > max_items:
            summary.append(f"...他{len(search_results) - max_items}件")
        return "\n".join(summary)

    def execute(self, state: AgentState) -> AgentState:
        """
        分析メソッドを実行し、結果をLLMで統合してレポートを生成する。

        Args:
            state: 現在の AgentState。

        Returns:
            分析・統合結果を反映した AgentState。
        """
        search_results = state.get("search_results")
        query = state.get("current_query")

        if search_results is None:  # 空リスト[] はOKとする
            return self._handle_error(state, "MissingInput", "検索結果が state に存在しません。")
        if not query:
            return self._handle_error(state, "MissingInput", "現在のクエリが state に存在しません。")

        if not self.analysis_methods:
            logger.warning(f"ノード '{self.node_name}' で実行する分析メソッドがありません。")
            state["analysis_results"] = {}
            state["synthesis_result"] = "分析メソッドが設定されていないため、レポートを生成できませんでした。"
            return state

        logger.info(f"ノード '{self.node_name}' を開始します。検索結果: {len(search_results)}件")

        analysis_outputs: Dict[str, Any] = {}
        # 分析対象データを作成 (例: 全検索結果のコンテンツを結合)
        # TODO: より洗練された分析対象データの準備方法を検討
        analysis_input_data = "\n\n".join(
            [
                f"Source: {res.get('source', 'N/A')} - {res.get('title', res.get('path', 'N/A'))}\nContent: {res.get('content', '')}"
                for res in search_results
                if res.get("content")  # コンテンツがあるもののみ
            ]
        )

        if not analysis_input_data:
            logger.warning("分析対象となるコンテンツを持つ検索結果がありませんでした。")
            analysis_input_data = "(分析対象データなし)"  # 分析メソッドには空でないことを示す

        for method in self.analysis_methods:
            method_name = method.method_name
            logger.info(f"分析メソッド '{method_name}' を実行します...")
            try:
                # メソッド固有のパラメータを渡すことも可能
                result = method(data=analysis_input_data)  # __call__ を利用
                analysis_outputs[method_name] = result
                logger.info(f"分析メソッド '{method_name}' が完了しました。")
            except Exception as e:
                logger.error(
                    f"分析メソッド '{method_name}' の実行中にエラーが発生しました: {e}",
                    exc_info=True,
                )
                # エラーが発生した場合、_handle_error を呼び出して処理を中断する
                return self._handle_error(
                    state,
                    error_code=f"{method_name.capitalize()}Error",  # 例: SummarizeError
                    message=f"分析メソッド '{method_name}' の実行に失敗しました: {e}",
                    exception=e,
                )

        state["analysis_results"] = analysis_outputs
        logger.info("全分析メソッドの実行が完了しました。レポート合成を開始します...")

        # レポート合成
        try:
            chain = self.synthesis_prompt | self.llm_client | self.output_parser
            synthesis_input = {
                "query": query,
                "analysis_results": "\n".join([f"- {k}: {v}" for k, v in analysis_outputs.items()]),
                "search_results_summary": self._format_search_results_summary(search_results),
            }
            synthesis_result = chain.invoke(synthesis_input)
            state["synthesis_result"] = synthesis_result
            logger.info("レポート合成が完了しました。")

        except Exception as e:
            logger.error(f"レポート合成中にエラーが発生しました: {e}", exc_info=True)
            return self._handle_error(
                state,
                "SynthesisError",
                f"レポート合成中にエラーが発生しました: {e}",
                exception=e,
            )

        state["replan_needed"] = False  # 分析・統合後は再計画不要
        return state
