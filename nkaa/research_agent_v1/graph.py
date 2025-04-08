#!/usr/bin/env python3
"""
graph.py – エージェントの全体構造および依存関係グラフを定義するモジュールである。
本実装はdocs/plan/research_agent_v1.mdおよびdocs/meta_plan/makefile_policy.mdなどの各種ドキュメントに沿って実装される。
langgraphライブラリを利用してグラフの構築を行う。

注意: 本ファイルの内容は.clinerulesに準拠している。また、開発者向けのコメントは「である調」を用いる。
"""

import logging
from datetime import datetime

# 状態を定義するためのTypedDict（必要に応じて）
from typing import Any, Dict, TypedDict

from langgraph.graph import END, StateGraph

# research_agent_v1.nodesから必要なクラスをインポート
from .nodes import (
    AnalysisSynthesisAgent,
    DataGatheringAgent,
    FinalCheckAgent,
    ReplanAgent,  # ReplanAgent を追加
)


# グラフの状態を定義
class AgentState(TypedDict):
    query: str
    options: Dict[str, Any]
    data_gathering_results: Dict[str, Any] | None
    analysis_results: Dict[str, Any] | None
    synthesis_results: Dict[str, Any] | None
    final_results: Dict[str, Any] | None
    final_check_results: Dict[str, Any] | None
    error: str | None
    # --- 再試行関連 ---
    retry_count: int  # 現在の再試行回数
    max_retries: int  # 最大再試行回数
    refined_query: str | None  # 再計画されたクエリ


# --- ノード関数 ---
# 各エージェントのrunメソッドはAgentStateを受け取り、更新部分を返す必要がある。
# nodes.pyのrunメソッドのシグネチャと戻り値を調整する必要がある。
# ここでは、ラッパー関数を使うか、nodes.py側を修正することを想定する。


def gather_data_node(state: AgentState) -> Dict[str, Any]:
    """データ収集ノードを実行するラッパー関数"""
    logging.debug("--- Running Data Gathering Node ---")
    agent = DataGatheringAgent()  # インスタンス化（DIも検討可能）
    try:
        # refined_query があればそちらを優先、なければ元の query を使用
        query_to_use = state.get("refined_query") or state["query"]
        logging.info(
            f"Using query for data gathering: '{query_to_use}'"
        )  # 使用するクエリをログ出力
        # nodes.pyのrunメソッドはinput_data辞書を受け取る想定なので合わせる
        # input_data には query_to_use を渡す
        input_data = {"query": query_to_use, "options": state["options"]}
        # nodes.pyのrunメソッドの戻り値が {'results': ..., 'state': ..., 'error': ...} の形式と仮定
        # agent.run には input_data を渡す (nodes.py側で refined_query を見る必要はない)
        output = agent.run(input_data)
        if output.get("error"):
            logging.error(f"Data gathering failed: {output['error']}")
            return {"error": output["error"]}
        logging.debug(f"Data gathering results: {output.get('results')}")
        return {"data_gathering_results": output.get("results")}
    except Exception as e:
        logging.exception("Exception during data gathering")
        return {"error": f"Data gathering exception: {e}"}


def analyze_synthesize_node(state: AgentState) -> Dict[str, Any]:
    """分析・統合ノードを実行するラッパー関数"""
    logging.debug("--- Running Analysis & Synthesis Node ---")
    if state.get("error"):  # 前のステップでエラーがあればスキップ
        return {}
    if not state.get("data_gathering_results"):
        logging.warning("No data gathering results found for analysis.")
        return {"error": "Missing data gathering results"}

    agent = AnalysisSynthesisAgent()  # インスタンス化
    try:
        # nodes.pyのrunメソッドはinput_data辞書を受け取る想定
        input_data = {"results": state["data_gathering_results"]}
        # nodes.pyのrunメソッドの戻り値が {'analysis': ..., 'synthesis': ..., 'state': ..., 'error': ...} と仮定
        output = agent.run(input_data)
        if output.get("error"):
            logging.error(f"Analysis/Synthesis failed: {output['error']}")
            return {"error": output["error"]}
        logging.debug(f"Analysis results: {output.get('analysis')}")
        logging.debug(f"Synthesis results: {output.get('synthesis')}")
        return {
            "analysis_results": output.get("analysis"),
            "synthesis_results": output.get("synthesis"),
        }
    except Exception as e:
        logging.exception("Exception during analysis/synthesis")
        return {"error": f"Analysis/Synthesis exception: {e}"}


def organize_results_node(state: AgentState) -> Dict[str, Any]:
    """最終結果を整理するノード"""
    logging.debug("--- Running Organize Results Node ---")
    if state.get("error"):  # エラーがあれば最終結果にも反映
        return {
            "final_results": {
                "status": "error",
                "message": state["error"],
                "timestamp": datetime.now().isoformat(),
            }
        }

    # 正常終了時の結果整理
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
    # final_results を返しつつ、エラー状態はクリアしない
    return {"final_results": final_results, "error": state.get("error")}


def final_check_node(state: AgentState) -> Dict[str, Any]:
    """最終チェックノードを実行するラッパー関数"""
    logging.debug("--- Running Final Check Node ---")
    if state.get("error"):  # 前のステップでエラーがあればスキップ
        # エラーがある場合、チェック結果は更新せず、既存のエラーを維持
        return {"error": state.get("error")}
    if (
        not state.get("final_results")
        or state["final_results"].get("status") == "error"
    ):
        logging.warning(
            "Skipping final check due to missing or error state in final_results."
        )
        # final_results にエラーがある場合はそれを維持
        return {"error": state.get("error") or "Missing or error in final_results"}

    agent = FinalCheckAgent()
    try:
        # nodes.py の FinalCheckAgent.run は input_data を受け取る
        # 必要な情報を渡す
        input_data = {
            "query": state["query"],
            "synthesis_results": state["synthesis_results"],
            # final_results も渡して、synthesis がない場合のエラーハンドリングに使う
            "final_results": state["final_results"],
        }
        # nodes.py の run の戻り値は {"final_check_results": ...} または {"check_error": ..., "final_check_results": ...}
        output = agent.run(input_data)

        # エラーがあれば state['error'] に設定
        if output.get("check_error"):
            logging.error(f"Final check failed: {output['check_error']}")
            # 既存のエラーがあればそれに追記、なければ新規設定
            current_error = state.get("error")
            new_error = f"Final Check Error: {output['check_error']}"
            combined_error = (
                f"{current_error}; {new_error}" if current_error else new_error
            )
            return {
                "final_check_results": output.get("final_check_results"),
                "error": combined_error,
            }
        else:
            # 成功時はチェック結果のみ返す (エラーは None のまま)
            return {
                "final_check_results": output.get("final_check_results"),
                "error": None,
            }  # 成功時はエラーをクリア

    except Exception as e:
        logging.exception("Exception during final check")
        error_msg = f"Final check exception: {e}"
        current_error = state.get("error")
        combined_error = f"{current_error}; {error_msg}" if current_error else error_msg
        return {"error": combined_error}


def replan_node(state: AgentState) -> Dict[str, Any]:
    """クエリ再計画ノードを実行するラッパー関数"""
    logging.debug("--- Running Replan Node ---")
    # エラーが発生している場合や、そもそもチェック結果がない場合はスキップ
    if state.get("error") or not state.get("final_check_results"):
        logging.warning(
            "Skipping replan due to existing error or missing check results."
        )
        # エラーを維持しつつ、再試行カウントは増やさないようにする
        # (エラー処理は handle_error ノードに任せる)
        return {"error": state.get("error", "Missing final_check_results for replan")}

    agent = ReplanAgent()
    try:
        # nodes.py の ReplanAgent.run は input_data を受け取る
        input_data = {
            "query": state["query"],
            "synthesis_results": state["synthesis_results"],
            "final_check_results": state["final_check_results"],
            "retry_count": state["retry_count"],  # 現在のカウントを渡す
        }
        # nodes.py の run の戻り値は {"refined_query": ..., "retry_count": ..., "error": ...}
        output = agent.run(input_data)

        if output.get("error"):
            logging.error(f"Replanning failed: {output['error']}")
            # エラーが発生したら、既存のエラーに追加
            current_error = state.get("error")
            new_error = f"Replanning Error: {output['error']}"
            combined_error = (
                f"{current_error}; {new_error}" if current_error else new_error
            )
            # refined_query は更新せず、エラーと更新された retry_count を返す
            return {
                "error": combined_error,
                "retry_count": output.get("retry_count", state["retry_count"]),
            }
        else:
            # 成功時は refined_query とインクリメントされた retry_count を返す
            logging.info(
                f"Replanning successful. New query: {output.get('refined_query')}"
            )
            return {
                "refined_query": output.get("refined_query"),
                "retry_count": output.get("retry_count"),
                "error": None,  # 成功時はエラーをクリア
            }

    except Exception as e:
        logging.exception("Exception during replanning")
        error_msg = f"Replanning exception: {e}"
        current_error = state.get("error")
        combined_error = f"{current_error}; {error_msg}" if current_error else error_msg
        # エラーが発生した場合も retry_count はインクリメントされている可能性があるためそのまま返す
        return {"error": combined_error, "retry_count": state.get("retry_count", 0)}


def handle_error_node(state: AgentState) -> Dict[str, Any]:
    """エラー処理ノード"""
    logging.error(f"--- Handling Error: {state.get('error', 'Unknown error')} ---")
    # 既にorganize_results_nodeでエラー時のfinal_resultsが設定されている場合もある
    if not state.get("final_results"):
        state["final_results"] = {
            "status": "error",
            "message": state.get("error", "Unknown error during workflow"),
            "timestamp": datetime.now().isoformat(),
        }
    # エラー状態をクリアしないように注意（ENDに遷移するため）
    return {"final_results": state["final_results"]}


# --- 条件付きエッジ用の関数 ---
def should_continue(state: AgentState) -> str:
    """エラー状態に基づいて次の遷移を決定する"""
    if state.get("error"):
        logging.warning(
            f"Workflow error detected: {state['error']}. Routing to handle_error."
        )
        return "handle_error"
    logging.debug("No error detected. Continuing workflow.")
    return "continue"


def check_and_decide_next_step(state: AgentState) -> str:
    """最終チェックの結果と再試行回数に基づいて次の遷移を決定する"""
    # まずエラーがないか確認
    if state.get("error"):
        logging.warning(
            f"Workflow error detected before final decision: {state['error']}. Routing to handle_error."
        )
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
        return "finish"
    elif evaluation == "不適合" and retry_count < max_retries:
        logging.warning(
            f"Final check failed (Attempt {retry_count + 1}/{max_retries}). Replanning query."
        )
        return "replan"
    elif evaluation == "不適合":
        logging.error(
            f"Final check failed after {max_retries} retries. Ending workflow with failure."
        )
        # 最大リトライ回数に達した場合はエラーとして扱う
        state["error"] = (
            f"Final check failed after {max_retries} retries. Reason: {final_check_results.get('reason', 'Unknown')}"
        )
        return "handle_error"  # エラーハンドリングノードへ
    else:  # evaluation が "スキップ" や "エラー" の場合など
        logging.error(
            f"Final check resulted in '{evaluation}'. Reason: {final_check_results.get('reason', 'Unknown')}. Routing to handle_error."
        )
        # 既にエラーがあるはずだが念のため設定
        if not state.get("error"):
            state["error"] = (
                f"Final check status: {evaluation}. Reason: {final_check_results.get('reason', 'Unknown')}"
            )
        return "handle_error"


# --- グラフ構築関数 ---
def build_agent_graph():
    """
    エージェントの依存関係グラフを構築する関数である。
    StateGraphを使用して状態遷移を定義する。
    """
    graph = StateGraph(AgentState)

    # ノードの追加
    graph.add_node("gather_data", gather_data_node)
    graph.add_node("analyze_synthesize", analyze_synthesize_node)
    graph.add_node("organize_results", organize_results_node)
    graph.add_node("final_check", final_check_node)
    graph.add_node("replan", replan_node)  # replan ノードを追加
    graph.add_node("handle_error", handle_error_node)

    # エントリーポイントの設定
    graph.set_entry_point("gather_data")

    # エッジの追加
    # 通常フロー: gather_data -> analyze_synthesize -> organize_results -> END
    # エラーフロー: * --(error)--> handle_error -> END

    # gather_data の後の遷移
    graph.add_conditional_edges(
        "gather_data",
        should_continue,
        {
            "continue": "analyze_synthesize",
            "handle_error": "handle_error",
        },
    )

    # analyze_synthesize の後の遷移
    graph.add_conditional_edges(
        "analyze_synthesize",
        should_continue,
        {
            "continue": "organize_results",
            "handle_error": "handle_error",
        },
    )

    # organize_results から final_check へ遷移
    graph.add_conditional_edges(
        "organize_results",
        should_continue,  # organize_results でエラーが発生する可能性も考慮
        {
            "continue": "final_check",
            "handle_error": "handle_error",
        },
    )

    # final_check の後の遷移 (新しい条件関数を使用)
    graph.add_conditional_edges(
        "final_check",
        check_and_decide_next_step,
        {
            "finish": END,  # 適合した場合
            "replan": "replan",  # 不適合でリトライ可能な場合
            "handle_error": "handle_error",  # エラーまたはリトライ上限の場合
        },
    )

    # replan から gather_data へ戻る (ループ)
    graph.add_edge("replan", "gather_data")

    # handle_error からは必ず終了
    graph.add_edge("handle_error", END)

    # TODO: nodes.pyの各Agentクラスのrunメソッドの戻り値が、
    # 上記のラッパー関数 (gather_data_node, analyze_synthesize_node) が期待する
    # 形式 (AgentStateの更新部分を含む辞書) と一致しているか確認・修正が必要。

    logging.info("Agent graph built successfully.")
    return graph
