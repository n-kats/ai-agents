import logging
from typing import Literal

from langgraph.graph import END, StateGraph

from nkaa.research_agent_v2.config.settings import Settings  # 設定をインポート
from nkaa.research_agent_v2.nodes.analysis_synthesis import AnalysisSynthesisNode
from nkaa.research_agent_v2.nodes.data_gathering import DataGatheringNode
from nkaa.research_agent_v2.nodes.final_check import FinalCheckNode
from nkaa.research_agent_v2.nodes.replan import ReplanNode
from nkaa.research_agent_v2.state import AgentState

logger = logging.getLogger(__name__)

# --- Conditional Edge Logic ---


# 条件分岐関数が設定オブジェクトを受け取れるようにラップする
def create_should_replan_condition(settings: Settings):
    def should_replan(state: AgentState) -> Literal["replan", "finish"]:
        """
        最終チェックの結果と試行回数に基づき、再計画が必要か、終了するかを決定する。
        エラーが発生した場合も終了とする。
        """
        if state.get("error_info"):
            logger.error(f"エラーが発生したため処理を終了します: {state['error_info']}")
            return "finish"  # エラー時は終了

        replan_needed = state.get("replan_needed", False)
        if replan_needed:
            max_attempts = settings.max_replan_attempts
            current_attempts = state.get(
                "replan_attempts", 0
            )  # ReplanNode でインクリメントされているはず
            if current_attempts >= max_attempts:
                logger.warning(
                    f"再計画の最大試行回数({max_attempts})に達しました。処理を終了します。"
                )
                return "finish"
            logger.info(
                f"最終チェック不合格、再計画を実行します (試行 {current_attempts + 1}/{max_attempts})。"
            )
            return "replan"
        else:
            logger.info("最終チェックに合格したため、処理を終了します。")
            return "finish"

    return should_replan


# --- Graph Builder ---


def build_graph(
    data_gathering_node: DataGatheringNode,
    analysis_synthesis_node: AnalysisSynthesisNode,
    final_check_node: FinalCheckNode,
    replan_node: ReplanNode,
    settings: Settings,  # DI: アプリケーション設定
) -> StateGraph:
    """
    research_agent_v2 の LangGraph StateGraph を構築する。

    Args:
        data_gathering_node: データ収集ノードのインスタンス。
        analysis_synthesis_node: 分析・統合ノードのインスタンス。
        final_check_node: 最終チェックノードのインスタンス。
        replan_node: 再計画ノードのインスタンス。
        settings: アプリケーション設定。

    Returns:
        構築された StateGraph オブジェクト (未コンパイル)。
    """
    workflow = StateGraph(AgentState)

    # 1. ノードを追加
    workflow.add_node(
        data_gathering_node.node_name, data_gathering_node
    )  # __call__ を使う
    workflow.add_node(analysis_synthesis_node.node_name, analysis_synthesis_node)
    workflow.add_node(final_check_node.node_name, final_check_node)
    workflow.add_node(replan_node.node_name, replan_node)

    # 2. エントリーポイントを設定
    workflow.set_entry_point(data_gathering_node.node_name)

    # 3. 通常のエッジを定義
    workflow.add_edge(data_gathering_node.node_name, analysis_synthesis_node.node_name)
    workflow.add_edge(analysis_synthesis_node.node_name, final_check_node.node_name)
    # 再計画後はデータ収集からやり直し
    workflow.add_edge(replan_node.node_name, data_gathering_node.node_name)

    # 4. 条件付きエッジを定義 (最終チェック後)
    # 設定オブジェクトを渡すために条件分岐関数を生成
    should_replan_condition = create_should_replan_condition(settings)
    workflow.add_conditional_edges(
        final_check_node.node_name,
        should_replan_condition,  # 生成した関数を使用
        {
            "replan": replan_node.node_name,
            "finish": END,
        },
    )
    # コンパイルは main.py で行う
    logger.info("research_agent_v2 StateGraph の構築が完了しました。")
    return workflow
