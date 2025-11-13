#!/usr/bin/env python3
"""
graph.py – research_agent_v1 のグラフ構造と状態遷移を定義する。
langgraph ライブラリを利用してグラフを構築する。
"""

import logging
from datetime import datetime
from typing import Any, Dict, TypedDict

from langgraph.graph import END, StateGraph

from nkaa.research_agent_v1.nodes import (
    AnalysisSynthesisAgent,
    DataGatheringAgent,
    FinalCheckAgent,
    ReplanAgent,
)


# グラフ全体で共有される状態を定義する
class AgentState(TypedDict):
    query: str
    options: Dict[str, Any]
    data_gathering_results: Dict[str, Any] | None
    analysis_results: Dict[str, Any] | None
    synthesis_results: Dict[str, Any] | None
    final_results: Dict[str, Any] | None
    final_check_results: Dict[str, Any] | None
    error: str | None
    # 再試行制御用の状態
    retry_count: int
    max_retries: int
    refined_query: str | None


# --- ノード関数 ---
# 各ノード関数は AgentState を受け取り、状態の更新部分を含む辞書を返す。
# 実際の処理は nodes.py 内の各 Agent クラスに委譲する。
# このラッパー関数群は、Agent クラスのインターフェース (input_data を受け取る) と
# StateGraph が要求するインターフェース (AgentState を受け取る) の差異を吸収する役割を持つ。


def gather_data_node(state: AgentState) -> Dict[str, Any]:
    """データ収集ノード: クエリに基づいて情報を収集する。"""
    logging.debug("--- Running Data Gathering Node ---")
    # DIコンテナ等を使わず直接インスタンス化しているが、将来的に変更する可能性はある
    agent = DataGatheringAgent()
    try:
        # 再計画されたクエリ (refined_query) があれば、それを優先して使用する
        query_to_use = state.get("refined_query") or state["query"]
        logging.info(f"Using query for data gathering: '{query_to_use}'")
        # DataGatheringAgent は input_data 形式の入力を期待するため、それに合わせる
        input_data = {"query": query_to_use, "options": state["options"]}
        # DataGatheringAgent.run の戻り値は {'results': ..., 'error': ...} を想定
        output = agent.run(input_data)
        if output.get("error"):
            logging.error(f"Data gathering failed: {output['error']}")
            # エラー発生時は error のみを返す (他の状態は更新しない)
            return {"error": output["error"]}
        logging.debug(f"Data gathering results: {output.get('data_gathering_results')}")
        # 成功時は data_gathering_results を更新する辞書を返す
        return {"data_gathering_results": output.get("data_gathering_results")}
    except Exception as e:
        logging.exception("Exception during data gathering")
        return {"error": f"Data gathering exception: {e}"}


def analyze_synthesize_node(state: AgentState) -> Dict[str, Any]:
    """分析・統合ノード: 収集されたデータを分析し、結果を統合する。"""
    logging.debug("--- Running Analysis & Synthesis Node ---")
    # 前のステップでエラーが発生していれば、このノードは実行せずに状態を維持する
    if state.get("error"):
        return {}
    if not state.get("data_gathering_results"):
        logging.warning("No data gathering results found for analysis.")
        return {"error": "Missing data gathering results"}

    agent = AnalysisSynthesisAgent()
    try:
        # AnalysisSynthesisAgent は input_data 形式の入力を期待
        input_data = {"results": state["data_gathering_results"]}
        # AnalysisSynthesisAgent.run の戻り値は {'analysis': ..., 'synthesis': ..., 'error': ...} を想定
        output = agent.run(input_data)
        if output.get("error"):
            logging.error(f"Analysis/Synthesis failed: {output['error']}")
            return {"error": output["error"]}
        logging.debug(f"Analysis results: {output.get('analysis_results')}")
        logging.debug(f"Synthesis results: {output.get('synthesis_results')}")
        # 成功時は analysis_results と synthesis_results を更新する辞書を返す
        return {
            "analysis_results": output.get("analysis_results"),
            "synthesis_results": output.get("synthesis_results"),
        }
    except Exception as e:
        logging.exception("Exception during analysis/synthesis")
        return {"error": f"Analysis/Synthesis exception: {e}"}


def organize_results_node(state: AgentState) -> Dict[str, Any]:
    """最終結果整理ノード: ワークフローの最終結果を整形する。"""
    logging.debug("--- Running Organize Results Node ---")
    # 途中でエラーが発生していた場合、エラー情報を含む最終結果を生成する
    if state.get("error"):
        return {
            "final_results": {
                "status": "error",
                "message": state["error"],
                "timestamp": datetime.now().isoformat(),
            }
        }

    # 正常終了時の最終結果を生成する
    final_results = {
        "query": state.get("query"),
        "options": state.get("options"),
        "data_gathering_results": state.get("data_gathering_results"),
        "analysis_results": state.get("analysis_results"),
        "synthesis_results": state.get("synthesis_results"),
        "status": "success",
        "timestamp": datetime.now().isoformat(),
    }
    logging.debug(f"Final organized results: {final_results}")
    # final_results を更新する辞書を返す (既存のエラー状態は維持される)
    return {"final_results": final_results}


def final_check_node(state: AgentState) -> Dict[str, Any]:
    """最終チェックノード: 生成された結果がクエリの意図に適合するか評価する。"""
    logging.debug("--- Running Final Check Node ---")
    # 前のステップでエラーが発生していればスキップ
    if state.get("error"):
        return {}
    # 最終結果が存在しない、またはエラー状態の場合はスキップ
    final_results = state.get("final_results")
    if not final_results or final_results.get("status") == "error":
        logging.warning("Skipping final check due to missing or error state in final_results.")
        # 既存のエラー状態を維持、なければエラーを設定
        return {"error": state.get("error") or "Missing or error in final_results"}

    agent = FinalCheckAgent()
    try:
        # FinalCheckAgent は input_data 形式の入力を期待
        input_data = {
            "query": state["query"],
            "synthesis_results": state["synthesis_results"],
            # final_results も渡して、synthesis がない場合のエラーハンドリングに使う
            "final_results": state["final_results"],
        }
        # FinalCheckAgent.run の戻り値は {"final_check_results": ..., "check_error": ...} を想定
        output = agent.run(input_data)

        # チェックでエラーが発生した場合 (FinalCheckAgent.run は 'check_error' キーでエラーを返す)
        if output.get("check_error"):
            logging.error(f"Final check failed: {output['check_error']}")
            # 既存のエラーがあれば追記、なければ新規設定
            current_error = state.get("error")
            new_error = f"Final Check Error: {output['check_error']}"
            combined_error = f"{current_error}; {new_error}" if current_error else new_error
            # final_check_results と更新された error を返す
            return {
                "final_check_results": output.get("final_check_results"),
                "error": combined_error,
            }
        else:
            # チェック成功時は final_check_results を更新し、エラーをクリアする
            return {
                "final_check_results": output.get("final_check_results"),
                "error": None,
            }

    except Exception as e:
        logging.exception("Exception during final check")
        error_msg = f"Final check exception: {e}"
        current_error = state.get("error")
        combined_error = f"{current_error}; {error_msg}" if current_error else error_msg
        return {"error": combined_error}


def replan_node(state: AgentState) -> Dict[str, Any]:
    """クエリ再計画ノード: 最終チェックで不適合だった場合にクエリを修正する。"""
    logging.debug("--- Running Replan Node ---")
    # エラーが発生している場合や、チェック結果がない場合はスキップ
    if state.get("error") or not state.get("final_check_results"):
        logging.warning("Skipping replan due to existing error or missing check results.")
        # エラーを維持し、再試行カウントは増やさない (エラー処理は handle_error ノードに任せる)
        return {"error": state.get("error", "Missing final_check_results for replan")}

    agent = ReplanAgent()
    try:
        # ReplanAgent は input_data 形式の入力を期待
        input_data = {
            "query": state["query"],
            "synthesis_results": state["synthesis_results"],
            "final_check_results": state["final_check_results"],
            "retry_count": state["retry_count"],
        }
        # ReplanAgent.run の戻り値は {"refined_query": ..., "retry_count": ..., "error": ...} を想定
        output = agent.run(input_data)

        if output.get("error"):
            logging.error(f"Replanning failed: {output['error']}")
            # エラーが発生したら、既存のエラーに追加
            current_error = state.get("error")
            new_error = f"Replanning Error: {output['error']}"
            combined_error = f"{current_error}; {new_error}" if current_error else new_error
            # refined_query は更新せず、エラーと更新された retry_count を返す
            return {
                "error": combined_error,
                "retry_count": output.get("retry_count", state["retry_count"]),
            }
        else:
            # 成功時は refined_query とインクリメントされた retry_count を返し、エラーをクリアする
            logging.info(f"Replanning successful. New query: {output.get('refined_query')}")
            return {
                "refined_query": output.get("refined_query"),
                "retry_count": output.get("retry_count"),
                "error": None,
            }

    except Exception as e:
        logging.exception("Exception during replanning")
        error_msg = f"Replanning exception: {e}"
        current_error = state.get("error")
        combined_error = f"{current_error}; {error_msg}" if current_error else error_msg
        # エラー発生時も retry_count はインクリメントされている可能性があるため、そのまま返す
        return {"error": combined_error, "retry_count": state.get("retry_count", 0)}


def handle_error_node(state: AgentState) -> Dict[str, Any]:
    """エラー処理ノード: ワークフロー中のエラーを集約し、最終結果に反映させる。"""
    logging.error(f"--- Handling Error: {state.get('error', 'Unknown error')} ---")
    # organize_results_node で既にエラー時の final_results が設定されている場合もあるため、
    # final_results が未設定の場合のみ、エラー情報を含む final_results を設定する。
    if not state.get("final_results"):
        state["final_results"] = {
            "status": "error",
            "message": state.get("error", "Unknown error during workflow"),
            "timestamp": datetime.now().isoformat(),
        }
    # このノードは END に遷移するため、エラー状態はクリアしない
    return {"final_results": state["final_results"]}


# --- 条件付きエッジ用の関数 ---
def should_continue(state: AgentState) -> str:
    """エラー状態に基づいて次の遷移先 ('continue' または 'handle_error') を決定する。"""
    if state.get("error"):
        logging.warning(f"Workflow error detected: {state['error']}. Routing to handle_error.")
        return "handle_error"
    logging.debug("No error detected. Continuing workflow.")
    return "continue"


def check_and_decide_next_step(state: AgentState) -> str:
    """最終チェックの結果と再試行回数に基づいて次の遷移先 ('finish', 'replan', 'handle_error') を決定する。"""
    # 先にエラーがないか確認
    if state.get("error"):
        logging.warning(f"Workflow error detected before final decision: {state['error']}. Routing to handle_error.")
        return "handle_error"

    final_check_results = state.get("final_check_results")
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 1)

    if not final_check_results:
        logging.error("Final check results are missing. Routing to handle_error.")
        # エラー状態を設定して handle_error に遷移させる
        state["error"] = "Missing final_check_results"
        return "handle_error"

    evaluation = final_check_results.get("evaluation")

    if evaluation == "適合":
        logging.info("Final check passed. Ending workflow.")
        return "finish"  # ワークフロー終了
    elif evaluation == "不適合" and retry_count < max_retries:
        logging.warning(f"Final check failed (Attempt {retry_count + 1}/{max_retries}). Replanning query.")
        return "replan"  # 再計画ノードへ
    elif evaluation == "不適合":
        logging.error(f"Final check failed after {max_retries} retries. Ending workflow with failure.")
        # 最大リトライ回数に達した場合はエラーとして扱う
        state["error"] = (
            f"Final check failed after {max_retries} retries. Reason: {final_check_results.get('reason', 'Unknown')}"
        )
        return "handle_error"  # エラー処理ノードへ
    else:  # evaluation が "スキップ" や予期せぬ値の場合
        logging.error(
            f"Final check resulted in unexpected status '{evaluation}'. Reason: {final_check_results.get('reason', 'Unknown')}. Routing to handle_error."
        )
        # 既にエラーがあるはずだが念のため設定
        if not state.get("error"):
            state["error"] = f"Final check status: {evaluation}. Reason: {final_check_results.get('reason', 'Unknown')}"
        return "handle_error"


# --- グラフ構築関数 ---
def build_agent_graph():
    """エージェントのワークフローグラフを構築する。"""
    graph = StateGraph(AgentState)

    # ノードをグラフに追加
    graph.add_node("gather_data", gather_data_node)
    graph.add_node("analyze_synthesize", analyze_synthesize_node)
    graph.add_node("organize_results", organize_results_node)
    graph.add_node("final_check", final_check_node)
    graph.add_node("replan", replan_node)
    graph.add_node("handle_error", handle_error_node)

    # エントリーポイントを設定
    graph.set_entry_point("gather_data")

    # 通常フローとエラーハンドリングのエッジを設定
    # 各ステップ後に should_continue でエラーチェックを行い、エラーがあれば handle_error へ分岐する

    graph.add_conditional_edges(
        "gather_data",
        should_continue,
        {"continue": "analyze_synthesize", "handle_error": "handle_error"},
    )
    graph.add_conditional_edges(
        "analyze_synthesize",
        should_continue,
        {"continue": "organize_results", "handle_error": "handle_error"},
    )
    graph.add_conditional_edges(
        "organize_results",
        should_continue,
        {"continue": "final_check", "handle_error": "handle_error"},
    )

    # 最終チェック後の分岐を設定
    graph.add_conditional_edges(
        "final_check",
        check_and_decide_next_step,
        {
            "finish": END,  # 適合 -> 終了
            "replan": "replan",  # 不適合 (リトライ可) -> 再計画
            "handle_error": "handle_error",  # 不適合 (リトライ不可) or エラー -> エラー処理
        },
    )

    # 再計画ノードからデータ収集ノードへ戻るループエッジ
    graph.add_edge("replan", "gather_data")

    # エラー処理ノードからは必ず終了
    graph.add_edge("handle_error", END)

    # TODO: nodes.py の各 Agent クラスの run メソッドの戻り値が、
    # このファイルのラッパー関数が期待する形式 (AgentState の更新部分を含む辞書) と一致していることを確認済み。

    logging.info("Agent graph built successfully.")
    return graph
