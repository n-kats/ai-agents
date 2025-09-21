import argparse
import logging
import logging.config  # dictConfig を使うために追加
import pprint
import sys
import uuid  # 追加

# Any をインポート
from typing import Any, Dict, List, Optional

# RunnableConfig をインポート
from langchain_core.runnables import RunnableConfig

# from langgraph.graph import CompiledGraph # 不要になった
from langgraph.checkpoint.memory import MemorySaver  # 追加

from nkaa.research_agent_v2.config.settings import (
    AnyAnalysisMethodConfig,  # 修正: 新しい Union 型名
    AnySearchMethodConfig,  # 修正: 新しい Union 型名
    Settings,
    load_settings,
)
from nkaa.research_agent_v2.graph import build_graph
from nkaa.research_agent_v2.llm_clients.client_provider import get_llm_client
from nkaa.research_agent_v2.methods.analysis import (
    KeywordExtractMethod,
    SummarizeMethod,
)
from nkaa.research_agent_v2.methods.base_method import (
    BaseAnalysisMethod,
    BaseSearchMethod,
)

# --- Method Implementations ---
# 検索メソッドをインポート
from nkaa.research_agent_v2.methods.search import (
    LocalSearchMethod,  # 実装した LocalSearchMethod をインポート
    WebSearchMethod,
)
from nkaa.research_agent_v2.nodes.analysis_synthesis import AnalysisSynthesisNode
from nkaa.research_agent_v2.nodes.data_gathering import DataGatheringNode
from nkaa.research_agent_v2.nodes.final_check import FinalCheckNode
from nkaa.research_agent_v2.nodes.replan import ReplanNode
from nkaa.research_agent_v2.state import AgentState

# Placeholder は不要になったためコメントアウトまたは削除
# class PlaceholderSearchMethod(BaseSearchMethod): ...
# class PlaceholderAnalysisMethod(BaseAnalysisMethod): ...


# --- Method Instantiation Logic ---


def instantiate_search_methods(
    configs: List[AnySearchMethodConfig],
    settings: Settings,  # 修正: 型ヒント
) -> List[BaseSearchMethod]:
    """設定に基づいて検索メソッドをインスタンス化する"""
    methods: List[BaseSearchMethod] = []
    # メソッド名とクラスのマッピング (型ヒントを修正)
    method_map: Dict[str, type] = {  # Type[BaseSearchMethod] -> type
        "web_search": WebSearchMethod,
        "local_search": LocalSearchMethod,  # 実装したクラスを使用
    }
    for config in configs:
        if config.enabled:
            method_class = method_map.get(config.method_name)
            if method_class:
                try:
                    # メソッド固有の設定を辞書に変換して渡す
                    method_settings_dict: Dict[str, Any] = config.settings.model_dump() if config.settings else {}
                    # メソッドの種類に応じて初期化方法を分岐
                    if config.method_name == "local_search":
                        # LocalSearchMethod は 'config' 引数を期待
                        methods.append(method_class(config=method_settings_dict))
                    elif config.method_name == "web_search":
                        # WebSearchMethod は 'settings' 引数を期待
                        methods.append(method_class(settings=method_settings_dict))
                    # 他の検索メソッドがあればここに追加
                    # else:
                    #     logging.warning(f"検索メソッド '{config.method_name}' の初期化方法が不明です。")
                    #     methods.append(method_class(config=method_settings_dict)) # 仮

                    logging.info(f"検索メソッド '{config.method_name}' をインスタンス化しました。")
                except Exception as e:
                    logging.error(
                        f"検索メソッド '{config.method_name}' のインスタンス化に失敗: {e}",
                        exc_info=True,
                    )
            else:
                logging.warning(f"未定義の検索メソッド名です: {config.method_name}")
    return methods


def instantiate_analysis_methods(
    configs: List[AnyAnalysisMethodConfig],
    settings: Settings,  # 修正: 型ヒント
) -> List[BaseAnalysisMethod]:
    """設定に基づいて分析メソッドをインスタンス化する"""
    methods: List[BaseAnalysisMethod] = []
    # get_llm_client に settings オブジェクト全体を渡すように修正
    llm_client = get_llm_client(settings)
    # メソッド名とクラスのマッピング (型ヒントを修正)
    method_map: Dict[str, type] = {  # Type[BaseAnalysisMethod] -> type
        "summarize": SummarizeMethod,
        "keyword_extract": KeywordExtractMethod,
    }
    for config in configs:
        if config.enabled:
            method_class = method_map.get(config.method_name)
            if method_class:
                try:
                    # メソッド固有の設定を辞書に変換して渡す
                    method_settings_dict: Dict[str, Any] = config.settings.model_dump() if config.settings else {}
                    # 分析メソッドに LLM クライアントとメソッド固有設定を渡す
                    methods.append(
                        method_class(
                            llm_client=llm_client,
                            settings=method_settings_dict,
                        )
                    )
                    logging.info(f"分析メソッド '{config.method_name}' をインスタンス化しました。")
                except Exception as e:
                    logging.error(
                        f"分析メソッド '{config.method_name}' のインスタンス化に失敗: {e}",
                        exc_info=True,
                    )
            else:
                logging.warning(f"未定義の分析メソッド名です: {config.method_name}")
    return methods


# --- Logging Setup ---


def setup_logging(log_level: str):
    """ロギングを設定する (dictConfig を使用)"""
    level = getattr(logging, log_level.upper(), "INFO")

    LOGGING_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,  # 既存のロガーを無効にしない
        "formatters": {
            "standard": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
        },
        "handlers": {
            "console": {
                "level": level,
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "stream": sys.stdout,
            },
        },
        "loggers": {
            "": {  # ルートロガー
                "handlers": ["console"],
                "level": level,
                "propagate": True,
            },
            # 必要に応じて特定のライブラリのログレベルを調整
            # "langchain": {
            #     "handlers": ["console"],
            #     "level": "WARNING",
            #     "propagate": False,
            # },
            # "langgraph": {
            #     "handlers": ["console"],
            #     "level": "INFO",
            #     "propagate": False,
            # },
        },
    }
    logging.config.dictConfig(LOGGING_CONFIG)
    logging.info(f"ロギング設定を dictConfig で適用しました (Level: {level})。")  # 設定適用後にINFOログ

    # Langchain や Langgraph のログレベルも調整する場合はここで行う (dictConfig内で設定推奨)
    # logging.getLogger("langchain").setLevel(logging.WARNING)
    # logging.getLogger("langgraph").setLevel(logging.INFO)


# --- Agent Execution ---


def run_agent(query: str, config_path: Optional[str] = None):
    """エージェントを実行するメイン関数"""
    try:
        # 1. 設定読み込み (setup_logging より先に実行)
        # config_path が None の場合のデフォルトパスを指定
        effective_config_path = config_path if config_path else "config.yaml"
        settings = load_settings(effective_config_path)
        # 2. ロギング設定 (設定読み込み後に実行)
        setup_logging(settings.log_level)
        logging.info("設定を読み込み、ロギングを設定しました。")
        # logging.debug(f"Loaded settings object: {settings}") # デバッグログ削除
        # logging.debug(f"Loaded settings JSON: {settings.model_dump_json(indent=2)}") # デバッグログ削除

        # 2. 依存関係のインスタンス化 (DI)
        # get_llm_client に settings オブジェクト全体を渡すように修正
        llm_client = get_llm_client(settings)
        logging.info(f"LLMクライアント ({settings.llm.provider}, {settings.llm.model_name}) を準備しました。")

        # 3. メソッドのインスタンス化
        search_methods = instantiate_search_methods(settings.search_methods, settings)
        analysis_methods = instantiate_analysis_methods(settings.analysis_methods, settings)

        if not search_methods:
            logging.warning("有効な検索メソッドが設定されていません。")
            # 検索メソッドがない場合は処理を続行できない可能性があるため、エラーにするか判断が必要
            # return # または raise Exception("No search methods enabled.")
        if not analysis_methods:
            logging.warning("有効な分析メソッドが設定されていません。")
            # 分析メソッドがない場合も同様

        # ノードのインスタンス化
        data_gathering_node = DataGatheringNode(search_methods=search_methods)
        analysis_synthesis_node = AnalysisSynthesisNode(analysis_methods=analysis_methods, llm_client=llm_client)
        final_check_node = FinalCheckNode(llm_client=llm_client)
        replan_node = ReplanNode(llm_client=llm_client)
        logging.info("全ノードをインスタンス化しました。")

        # 3. グラフ構築
        workflow = build_graph(
            data_gathering_node=data_gathering_node,
            analysis_synthesis_node=analysis_synthesis_node,
            final_check_node=final_check_node,
            replan_node=replan_node,
            settings=settings,
        )
        # グラフをコンパイル (MemorySaver を使用)
        memory = MemorySaver()
        app = workflow.compile(checkpointer=memory)
        logging.info("グラフをコンパイルしました (MemorySaver 使用)。")

        # 4. 初期状態の準備
        initial_state: AgentState = {
            "initial_query": query,
            "current_query": query,
            "search_plan": None,
            "search_results": [],
            "analysis_results": {},
            "synthesis_result": None,
            "final_check_passed": None,
            "replan_needed": False,
            "error_info": None,
            "replan_attempts": 0,  # 不足していたキーを追加
        }
        logging.info(f"初期クエリ: '{query}' でエージェントを実行します。")

        # 5. グラフ実行
        final_state = None
        if app is None:
            logging.error("グラフのコンパイルに失敗したため、実行できません。")
            raise RuntimeError("Graph compilation failed.")

        # ストリームで実行し、各ステップの状態を表示する (デバッグに有用)
        # 一意なスレッドIDを生成
        thread_id = str(uuid.uuid4())
        # config を RunnableConfig で型付け
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        for step_state in app.stream(initial_state, config=config):
            state_key = list(step_state.keys())[0]
            current_state_data = step_state[state_key]
            logging.info(f"--- ステップ: {state_key} ---")
            # logging.debug(pprint.pformat(current_state_data)) # 詳細な状態を出力
            # 簡易表示:
            print(f"[{state_key}] Current Query: {current_state_data.get('current_query')}")
            if current_state_data.get("error_info"):
                print(f"  ERROR: {current_state_data['error_info']}")
            if state_key == "data_gathering":
                print(f"  Search Results Count: {len(current_state_data.get('search_results', []))}")
            if state_key == "analysis_synthesis":
                print(f"  Analysis Results Keys: {list(current_state_data.get('analysis_results', {}).keys())}")
                print(f"  Synthesis Result Length: {len(current_state_data.get('synthesis_result', ''))}")
            if state_key == "final_check":
                print(f"  Final Check Passed: {current_state_data.get('final_check_passed')}")
            if state_key == "replan":
                print("  Replanning...")

            final_state = current_state_data  # 最後の状態を保持

        # 6. 最終結果の出力
        print("\n--- 最終結果 ---")
        if final_state:
            if final_state.get("error_info"):
                print("エラーが発生しました:")
                pprint.pprint(final_state["error_info"])
            elif final_state.get("final_check_passed") is False:
                print("最終チェックで不合格となりました。レポート:")
                print(final_state.get("synthesis_result", "(レポートなし)"))
                print("\n(再計画の試行が必要だった可能性があります)")
            else:
                print("生成されたレポート:")
                print(final_state.get("synthesis_result", "(レポートなし)"))
        else:
            print("エージェントが最終状態に到達しませんでした。")

    except Exception as e:
        logging.error(f"エージェントの実行中に予期せぬエラーが発生しました: {e}", exc_info=True)
        sys.exit(1)


# --- Entry Point ---


def main():
    """コマンドライン引数を処理し、エージェントを実行する"""
    parser = argparse.ArgumentParser(description="Research Agent v2")
    parser.add_argument("query", type=str, help="調査したい初期クエリ")
    parser.add_argument("-c", "--config", type=str, default=None, help="設定ファイル(YAML/TOML)のパス")
    args = parser.parse_args()

    run_agent(query=args.query, config_path=args.config)


if __name__ == "__main__":
    main()
