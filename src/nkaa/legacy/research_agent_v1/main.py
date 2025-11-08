#!/usr/bin/env python3
"""
research_agent_v1 のメイン実行ファイル。
グラフの構築、コンパイル、実行を行う。
"""

import argparse
import json
import logging
import os
import pprint
from datetime import datetime

from dotenv import load_dotenv

from nkaa.research_agent_v1.graph import AgentState, build_agent_graph

# .env ファイルから環境変数を読み込む
load_dotenv()

# nodes モジュールは直接使用しないが、AgentState の型定義などで間接的に参照されるため import は維持する
# from .nodes import AnalysisSynthesisAgent, DataGatheringAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main():
    """メイン関数: グラフを構築し、実行する。"""
    parser = argparse.ArgumentParser(description="Research Agent v1")
    parser.add_argument("-q", "--query", type=str, help="The question to ask the agent.", required=False)
    parser.add_argument(
        "--max-retries",
        type=int,
        default=1,
        help="Maximum number of retries if the final check fails.",
    )
    parser.add_argument(
        "--graph-png",
        type=str,
        default=None,
        help="Path to save the graph visualization PNG file.",
    )
    parser.add_argument(
        "--output-detail",
        type=str,
        default=f"_output/{datetime.now().strftime('%Y%m%d%H%M%S')}.json",
        help="Path to save the detailed output in JSON format.",
    )
    args = parser.parse_args()
    logging.info(f"Arguments: {args}")

    # グラフを構築
    agent_graph = build_agent_graph()

    # グラフをコンパイル
    app = agent_graph.compile()
    logging.info("エージェントグラフの構築・コンパイル完了")

    # クエリが指定されている場合のみグラフを実行
    if args.query:
        logging.info(f"Executing graph for query: {args.query}")
        initial_state: AgentState = {
            "query": args.query,
            "options": {"search_depth": "advanced"},
            "data_gathering_results": None,
            "analysis_results": None,
            "synthesis_results": None,
            "final_results": None,
            "final_check_results": None,
            "error": None,
            "retry_count": 0,
            "max_retries": args.max_retries,
            "refined_query": None,
        }
        logging.info(f"Initial State: {pprint.pformat(initial_state)}")

        try:
            logging.info("--- Starting Graph Execution ---")
            # invoke() を使うと最終状態のみ取得できるが、ここでは stream() を使用する
            # final_state = app.invoke(initial_state)

            # stream() を使用して、各ステップの出力を確認しつつ最終状態を構築する
            final_state_accumulator = initial_state.copy()
            logging.info("--- Starting Graph Execution Stream ---")
            for step_output in app.stream(initial_state):
                node_name = list(step_output.keys())[0]
                node_output = step_output[node_name]
                logging.info(f"--- Node: {node_name} ---")
                logging.info(f"Output/Update: {pprint.pformat(node_output)}")
                # AgentState 型で定義されているキーのみを更新対象とする
                valid_keys = AgentState.__annotations__.keys()
                update_dict = {k: v for k, v in node_output.items() if k in valid_keys}
                final_state_accumulator.update(update_dict)

            logging.info("--- Graph Execution Finished ---")
            logging.info("\n調査結果:")
            final_results = final_state_accumulator.get("final_results")
            final_check_results = final_state_accumulator.get("final_check_results")
            if final_results:
                logging.info(f"調査結果: {pprint.pformat(final_results)}")
            if final_check_results:
                logging.info(f"最終確認結果: {pprint.pformat(final_check_results)}")
            if not final_results and not final_check_results:
                logging.info("調査結果がありません。")

            output_path = args.output_detail
            # 出力先ディレクトリを作成
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as json_file:
                json.dump(final_state_accumulator, json_file, ensure_ascii=False, indent=4)
            logging.info(f"詳細な調査結果が {output_path} に保存されました。")

            if final_state_accumulator.get("error"):
                logging.error(f"\nFinal Error State: {final_state_accumulator['error']}")

        except Exception as e:
            logging.error(f"\nError during graph execution: {e}", exc_info=True)
    else:
        logging.info("No query provided, skipping graph execution.")

    # グラフ構造の可視化 (--graph-png が指定された場合)
    if args.graph_png:
        try:
            # 可視化には graphviz と pygraphviz が必要
            # CompiledGraph (app) から DrawableGraph を取得し、PNG を描画する
            png_data = app.get_graph().draw_png()
            with open(args.graph_png, "wb") as f:
                f.write(png_data)
            logging.info(f"\nGraph visualization saved to {args.graph_png}")
        except ImportError:
            # 依存ライブラリがない場合は警告を表示し、可視化をスキップする
            logging.warning("\nInstall graphviz and pygraphviz to visualize the graph. Skipping visualization.")
        except Exception as e:
            logging.error(f"\nError generating graph visualization: {e}", exc_info=True)


if __name__ == "__main__":
    main()
