#!/usr/bin/env python3
"""
research_agent_v1 のメイン実行ファイル。
グラフの構築、コンパイル、実行を行う。
"""

import argparse  # 追加
import json
import logging
import pprint

from dotenv import load_dotenv  # 追加

# research_agent_v1 のコンポーネントをインポート
from nkaa.research_agent_v1.graph import AgentState, build_agent_graph

# .env ファイルから環境変数を読み込む
load_dotenv()  # 追加

# nodesは直接使わないが、型ヒントや理解のために残しても良い
# from .nodes import AnalysisSynthesisAgent, DataGatheringAgent

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def main():
    """メイン関数: グラフを構築し、実行例を示す。"""
    # コマンドライン引数をパース
    parser = argparse.ArgumentParser(description="Research Agent v1: Ask a question.")
    parser.add_argument("query", type=str, help="The question to ask the agent.")
    parser.add_argument(  # 追加
        "--max-retries",
        type=int,
        default=1,
        help="Maximum number of retries if the final check fails.",
    )
    args = parser.parse_args()
    logging.info(f"Received query: {args.query}, Max retries: {args.max_retries}")

    # グラフを構築 (引数は不要になった)
    agent_graph = build_agent_graph()

    # グラフをコンパイル
    # compile() は呼び出さないポリシーに従い、ここでは実行しないが、
    # 実行のためにはコンパイルが必要
    app = agent_graph.compile()
    logging.info("エージェントグラフの構築・コンパイル完了")

    # グラフの実行例（テスト用）
    # AgentStateに必要な初期値を設定
    initial_state: AgentState = {
        "query": args.query,
        "options": {"search_depth": "deep"},
        "data_gathering_results": None,
        "analysis_results": None,
        "synthesis_results": None,
        "final_results": None,
        "final_check_results": None,  # 追加
        "error": None,
        "retry_count": 0,  # 追加
        "max_retries": args.max_retries,  # 追加
        "refined_query": None,  # 追加
    }
    logging.info(f"Initial State: {pprint.pformat(initial_state)}")

    try:
        # コンパイルされたグラフを実行
        logging.info("--- Starting Graph Execution ---")
        # final_state = app.invoke(initial_state) # invokeで最終結果のみ取得

        # ストリームで各ステップの結果を確認しつつ、状態を蓄積
        final_state_accumulator = initial_state.copy()  # 初期状態で開始
        last_node_output = None
        logging.info("--- Starting Graph Execution Stream ---")
        for step_output in app.stream(initial_state):
            node_name = list(step_output.keys())[0]
            node_output = step_output[node_name]
            logging.info(f"--- Node: {node_name} ---")
            logging.info(f"Output/Update: {pprint.pformat(node_output)}")
            # AgentState 型のキーのみを更新対象とする
            valid_keys = AgentState.__annotations__.keys()
            update_dict = {k: v for k, v in node_output.items() if k in valid_keys}
            final_state_accumulator.update(update_dict)  # 有効なキーで状態を更新
            last_node_output = node_output  # 最後のノード出力を保持 (デバッグ用)

        logging.info("--- Graph Execution Finished ---")
        logging.info("\nFinal Accumulated Workflow State:")
        logging.info(
            pprint.pformat(final_state_accumulator)
        )  # 蓄積された最終状態を出力

        # 最終的なエラーがあれば表示
        if final_state_accumulator.get("error"):
            logging.error(f"\nFinal Error State: {final_state_accumulator['error']}")

    except Exception as e:
        logging.error(f"\nError during graph execution: {e}", exc_info=True)

    # グラフ構造の可視化（必要に応じて）
    # try:
    #     # graphvizとpygraphvizが必要
    #     png_data = agent_graph.get_graph().draw_mermaid_png()
    #     with open("research_agent_v1_graph.png", "wb") as f:
    #         f.write(png_data)
    #     logging.info("\nGraph visualization saved to research_agent_v1_graph.png")
    # except ImportError:
    #     logging.warning("\nInstall graphviz and pygraphviz to visualize the graph.")
    # except Exception as e:
    #     logging.error(f"\nError generating graph visualization: {e}", exc_info=True)


if __name__ == "__main__":
    main()
