# -*- coding: utf-8 -*-
"""research_agent_v2.nodes.data_gathering モジュールのテスト."""

import unittest
from unittest.mock import MagicMock  # call をインポート

# BaseSearchMethod をインポート
from nkaa.legacy.research_agent_v2.methods.base_method import BaseSearchMethod

# インポートを有効化
from nkaa.legacy.research_agent_v2.nodes.data_gathering import DataGatheringNode
from nkaa.legacy.research_agent_v2.state import AgentState, StructuredError


class TestDataGatheringNode(unittest.TestCase):
    """nodes.data_gathering.DataGatheringNode のテストクラス."""

    def setUp(self):
        """テスト前のセットアップ."""
        # 検索メソッドのモックを作成
        self.mock_web_search = MagicMock(spec=BaseSearchMethod)
        self.mock_web_search.method_name = "web_search"
        self.mock_local_search = MagicMock(spec=BaseSearchMethod)
        self.mock_local_search.method_name = "local_search"
        self.mock_search_methods = [self.mock_web_search, self.mock_local_search]

        # DataGatheringNode のインスタンス化
        self.node = DataGatheringNode(search_methods=self.mock_search_methods)

    def test_data_gathering_node_call_success(self):
        """DataGatheringNode の __call__ メソッド (成功時) のテスト."""
        # 準備
        initial_state: AgentState = {
            "current_query": "test query",
            "search_results": [],
            # 他の必須キー
            "initial_query": "iq",
            "search_plan": None,
            "analysis_results": {},
            "synthesis_result": None,
            "final_check_passed": None,
            "replan_needed": False,
            "error_info": None,
            "replan_attempts": 0,
        }
        web_results = [{"source": "web", "content": "web result 1"}]
        local_results = [{"source": "local", "content": "local result 1"}]

        self.mock_web_search.return_value = web_results
        self.mock_local_search.return_value = local_results

        # 実行
        result_state = self.node(initial_state)

        # 検証
        self.mock_web_search.assert_called_once_with(query="test query")
        self.mock_local_search.assert_called_once_with(query="test query")

        expected_results = [
            {"source": "web", "content": "web result 1", "search_method": "web_search"},
            {
                "source": "local",
                "content": "local result 1",
                "search_method": "local_search",
            },
        ]
        self.assertEqual(result_state["search_results"], expected_results)
        self.assertIsNone(result_state["error_info"])
        self.assertFalse(result_state["replan_needed"])

    def test_data_gathering_node_search_method_error(self):
        """検索メソッド実行中にエラーが発生した場合のテスト."""
        initial_state: AgentState = {
            "current_query": "test query",
            "search_results": [],
            # 他の必須キー
            "initial_query": "iq",
            "search_plan": None,
            "analysis_results": {},
            "synthesis_result": None,
            "final_check_passed": None,
            "replan_needed": False,
            "error_info": None,
            "replan_attempts": 0,
        }
        error_message = "Web search failed"
        self.mock_web_search.side_effect = Exception(error_message)  # web_search でエラー
        self.mock_local_search.return_value = [{"content": "local"}]  # local_search は呼ばれないはず

        # 実行
        result_state = self.node(initial_state)

        # 検証
        self.mock_web_search.assert_called_once_with(query="test query")  # web_search は呼ばれる
        self.mock_local_search.assert_not_called()  # local_search は呼ばれない

        self.assertIsInstance(result_state["error_info"], StructuredError)
        self.assertEqual(result_state["error_info"].node_name, "data_gathering")
        self.assertEqual(result_state["error_info"].error_code, "Web_searchError")  # メソッド名から生成
        self.assertIn(error_message, result_state["error_info"].message)
        # search_results は空のままのはず
        self.assertEqual(result_state["search_results"], [])

    def test_data_gathering_node_missing_input(self):
        """入力 (current_query) が欠損している場合のテスト."""
        initial_state: AgentState = {
            "current_query": None,  # クエリなし
            "search_results": [],
            # 他の必須キー
            "initial_query": "iq",
            "search_plan": None,
            "analysis_results": {},
            "synthesis_result": None,
            "final_check_passed": None,
            "replan_needed": False,
            "error_info": None,
            "replan_attempts": 0,
        }

        result_state = self.node(initial_state)

        self.mock_web_search.assert_not_called()
        self.mock_local_search.assert_not_called()
        self.assertIsInstance(result_state["error_info"], StructuredError)
        self.assertEqual(result_state["error_info"].error_code, "MissingInput")
        self.assertIn("検索クエリ", result_state["error_info"].message)

    def test_data_gathering_node_no_methods(self):
        """検索メソッドが指定されていない場合のテスト."""
        node_no_methods = DataGatheringNode(search_methods=[])  # 空リストで初期化
        initial_state: AgentState = {
            "current_query": "test query",
            "search_results": None,  # 初期値は None かもしれない
            # 他の必須キー
            "initial_query": "iq",
            "search_plan": None,
            "analysis_results": {},
            "synthesis_result": None,
            "final_check_passed": None,
            "replan_needed": False,
            "error_info": None,
            "replan_attempts": 0,
        }

        result_state = node_no_methods(initial_state)

        self.assertEqual(result_state["search_results"], [])  # 空リストが設定される
        self.assertIsNone(result_state["error_info"])  # エラーではない


if __name__ == "__main__":
    unittest.main()
