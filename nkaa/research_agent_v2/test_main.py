# -*- coding: utf-8 -*-
"""research_agent_v2.main モジュールのテスト."""

import unittest
from unittest.mock import ANY, MagicMock, patch  # ANY をインポート

from langgraph.graph import StateGraph  # StateGraph をインポート

from nkaa.research_agent_v2.config.settings import Settings

# main 内の関数やクラスをインポート
from nkaa.research_agent_v2.main import run_agent
from nkaa.research_agent_v2.state import AgentState, StructuredError


# run_agent 内で呼ばれる関数をまとめてモック
@patch("nkaa.research_agent_v2.main.load_settings")
@patch("nkaa.research_agent_v2.main.setup_logging")
@patch("nkaa.research_agent_v2.main.get_llm_client")
@patch("nkaa.research_agent_v2.main.instantiate_search_methods")
@patch("nkaa.research_agent_v2.main.instantiate_analysis_methods")
@patch("nkaa.research_agent_v2.main.build_graph")
@patch("langgraph.graph.StateGraph.compile")  # graph.compile をモック
@patch("nkaa.research_agent_v2.main.uuid.uuid4")  # uuid4 をモック
@patch("builtins.print")  # print 出力を抑制・検証
class TestRunAgent(unittest.TestCase):
    """main.py の run_agent 関数のテストクラス."""

    def test_run_agent_success(
        self,
        mock_print,
        mock_uuid4,
        mock_compile,
        mock_build_graph,
        mock_inst_analysis,
        mock_inst_search,
        mock_get_llm,
        mock_setup_logging,
        mock_load_settings,
    ):
        """run_agent が正常に実行されるかのテスト."""
        # --- モックの設定 ---
        mock_settings = MagicMock(spec=Settings)
        mock_settings.log_level = "INFO"
        # llm 属性とその中の属性を設定
        mock_settings.llm = MagicMock()
        mock_settings.llm.provider = "mock_provider"
        mock_settings.llm.model_name = "mock_model"
        # search_methods, analysis_methods も設定 (空リストでも可)
        mock_settings.search_methods = []
        mock_settings.analysis_methods = []
        mock_load_settings.return_value = mock_settings

        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        mock_search_methods = [MagicMock()]
        mock_inst_search.return_value = mock_search_methods
        mock_analysis_methods = [MagicMock()]
        mock_inst_analysis.return_value = mock_analysis_methods

        mock_graph = MagicMock(spec=StateGraph)
        mock_build_graph.return_value = mock_graph

        mock_app = MagicMock()
        mock_compile.return_value = mock_app  # compile が app を返す

        # stream の戻り値 (最終状態)
        final_success_state: AgentState = {
            "initial_query": "test query",
            "current_query": "test query",
            "synthesis_result": "Successful Report",
            "final_check_passed": True,
            "error_info": None,
            # 他のキーも必要に応じて設定
            "search_plan": None,
            "search_results": [],
            "analysis_results": {},
            "replan_needed": False,
            "replan_attempts": 0,
        }
        # stream はイテラブルを返す (最後の要素が最終状態)
        mock_app.stream.return_value = [{"final_check": final_success_state}]

        mock_uuid4.return_value = "test-uuid"  # 固定のUUIDを返す

        # --- 実行 ---
        run_agent("test query")

        # --- 検証 ---
        mock_load_settings.assert_called_once_with("config.yaml")  # デフォルトパス
        mock_setup_logging.assert_called_once_with("INFO")
        mock_get_llm.assert_called_once_with(mock_settings)
        mock_inst_search.assert_called_once_with(
            mock_settings.search_methods, mock_settings
        )
        mock_inst_analysis.assert_called_once_with(
            mock_settings.analysis_methods, mock_settings
        )
        mock_build_graph.assert_called_once_with(
            data_gathering_node=ANY,
            analysis_synthesis_node=ANY,
            final_check_node=ANY,
            replan_node=ANY,
            settings=mock_settings,
        )
        mock_compile.assert_called_once_with(checkpointer=ANY)  # MemorySaver が渡される

        # stream 呼び出しの検証
        expected_initial_state: AgentState = {
            "initial_query": "test query",
            "current_query": "test query",
            "search_plan": None,
            "search_results": [],
            "analysis_results": {},
            "synthesis_result": None,
            "final_check_passed": None,
            "replan_needed": False,
            "error_info": None,
            "replan_attempts": 0,
        }
        expected_config = {"configurable": {"thread_id": "test-uuid"}}
        mock_app.stream.assert_called_once_with(
            expected_initial_state, config=expected_config
        )

        # print 呼び出しの検証 (一部)
        mock_print.assert_any_call("\n--- 最終結果 ---")
        mock_print.assert_any_call("生成されたレポート:")
        mock_print.assert_any_call("Successful Report")

    @patch("sys.exit")  # sys.exit をモック
    def test_run_agent_setup_error(
        self,
        mock_exit,
        mock_print,
        mock_uuid4,
        mock_compile,
        mock_build_graph,
        mock_inst_analysis,
        mock_inst_search,
        mock_get_llm,
        mock_setup_logging,
        mock_load_settings,
    ):
        """run_agent のセットアップ中にエラーが発生した場合のテスト."""
        # --- モックの設定 ---
        error_message = "Failed to load settings"
        mock_load_settings.side_effect = RuntimeError(
            error_message
        )  # 設定読み込みでエラー

        # --- 実行 ---
        run_agent("test query")

        # --- 検証 ---
        mock_load_settings.assert_called_once()  # load_settings は呼ばれる
        mock_setup_logging.assert_not_called()  # それ以降は呼ばれない
        mock_get_llm.assert_not_called()
        # ... 他の関数も呼ばれない ...
        mock_exit.assert_called_once_with(1)  # sys.exit(1) が呼ばれる

    def test_run_agent_error_in_graph(
        self,
        mock_print,
        mock_uuid4,
        mock_compile,
        mock_build_graph,
        mock_inst_analysis,
        mock_inst_search,
        mock_get_llm,
        mock_setup_logging,
        mock_load_settings,
    ):
        """グラフ実行中にエラーが発生した場合のテスト."""
        # --- モックの設定 (成功時と同様) ---
        mock_settings = MagicMock(spec=Settings)
        mock_settings.log_level = "INFO"
        # llm 属性とその中の属性を設定
        mock_settings.llm = MagicMock()
        mock_settings.llm.provider = "mock_provider_error"
        mock_settings.llm.model_name = "mock_model_error"
        mock_settings.search_methods = []
        mock_settings.analysis_methods = []
        mock_load_settings.return_value = mock_settings
        mock_get_llm.return_value = MagicMock()
        mock_inst_search.return_value = [MagicMock()]
        mock_inst_analysis.return_value = [MagicMock()]
        mock_build_graph.return_value = MagicMock(spec=StateGraph)
        mock_app = MagicMock()
        mock_compile.return_value = mock_app

        # stream の戻り値 (エラー状態)
        error_info = StructuredError(
            node_name="some_node", error_code="SomeError", message="Error in node"
        )
        final_error_state: AgentState = {
            "initial_query": "test query",
            "current_query": "test query",
            "error_info": error_info,
            # 他のキー
            "search_plan": None,
            "search_results": [],
            "analysis_results": {},
            "synthesis_result": None,
            "final_check_passed": None,
            "replan_needed": False,
            "replan_attempts": 0,
        }
        mock_app.stream.return_value = [{"error_node": final_error_state}]
        mock_uuid4.return_value = "test-uuid-error"

        # --- 実行 ---
        run_agent("test query")

        # --- 検証 ---
        # セットアップ関数は呼ばれる
        mock_load_settings.assert_called_once()
        mock_setup_logging.assert_called_once()
        mock_get_llm.assert_called_once()
        mock_inst_search.assert_called_once()
        mock_inst_analysis.assert_called_once()
        mock_build_graph.assert_called_once()
        mock_compile.assert_called_once()
        mock_app.stream.assert_called_once()  # stream も呼ばれる

        # print 呼び出しの検証 (一部)
        mock_print.assert_any_call("\n--- 最終結果 ---")
        mock_print.assert_any_call("エラーが発生しました:")
        # pprint.pprint が呼ばれるので、その引数を検証するのは少し複雑
        # ここではエラー情報を含む出力があったことだけ確認
        # self.assertTrue(any("SomeError" in str(call_args) for call_args in mock_print.call_args_list))


if __name__ == "__main__":
    unittest.main()
