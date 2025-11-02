# -*- coding: utf-8 -*-
"""research_agent_v2.nodes.analysis_synthesis モジュールのテスト."""

import unittest
from unittest.mock import MagicMock, patch  # ANY をインポート

# BaseChatModel, BaseAnalysisMethod をインポート
from langchain_core.language_models import BaseChatModel

from nkaa.legacy.research_agent_v2.methods.base_method import BaseAnalysisMethod

# インポートを有効化
from nkaa.legacy.research_agent_v2.nodes.analysis_synthesis import AnalysisSynthesisNode
from nkaa.legacy.research_agent_v2.state import AgentState, StructuredError


class TestAnalysisSynthesisNode(unittest.TestCase):
    """nodes.analysis_synthesis.AnalysisSynthesisNode のテストクラス."""

    def setUp(self):
        """テスト前のセットアップ."""
        patcher = patch("nkaa.legacy.research_agent_v2.utils.prompt_loader.load_prompt_template")
        self.addCleanup(patcher.stop)
        self.mock_load_prompt = patcher.start()
        self.mock_load_prompt.return_value = "合成プロンプト: {query} {analysis_results} {search_results_summary}"
        self.mock_llm_client = MagicMock(spec=BaseChatModel)

        # 分析メソッドのモックを作成
        self.mock_summarize = MagicMock(spec=BaseAnalysisMethod)
        self.mock_summarize.method_name = "summarize"
        self.mock_keyword = MagicMock(spec=BaseAnalysisMethod)
        self.mock_keyword.method_name = "keyword_extract"
        self.mock_analysis_methods = [self.mock_summarize, self.mock_keyword]

        # AnalysisSynthesisNode のインスタンス化
        self.node = AnalysisSynthesisNode(
            analysis_methods=self.mock_analysis_methods,
            llm_client=self.mock_llm_client,
        )

    def test_analysis_synthesis_node_call_success(self):
        """AnalysisSynthesisNode の __call__ メソッド (成功時) のテスト."""
        # 準備
        initial_state: AgentState = {
            "current_query": "test query",
            "search_results": [
                {"source": "web", "title": "Doc 1", "content": "Content of doc 1."},
                {
                    "source": "local",
                    "path": "/path/doc2",
                    "content": "Content of doc 2.",
                },
                {"source": "web", "title": "Doc 3", "content": ""},  # コンテンツなし
            ],
            "analysis_results": {},
            "synthesis_result": None,
            "initial_query": "initial query",  # 他の必須キーも設定
            "search_plan": None,
            "final_check_passed": None,
            "replan_needed": False,
            "error_info": None,
            "replan_attempts": 0,
        }
        summary_result = "This is the summary."
        keyword_result = ["keyword1", "keyword2"]
        synthesis_report = "Final synthesized report."

        self.mock_summarize.return_value = summary_result
        self.mock_keyword.return_value = keyword_result
        # LLM (合成用) のモック設定
        # BaseChatModel の invoke は直接文字列を返さないため、content 属性を持つオブジェクトを返す
        mock_llm_response = MagicMock()
        mock_llm_response.content = synthesis_report
        self.mock_llm_client.invoke.return_value = mock_llm_response

        # 実行
        result_state = self.node(initial_state)

        # 検証
        # 分析メソッド呼び出し確認
        expected_analysis_input = (
            "Source: web - Doc 1\nContent: Content of doc 1.\n\nSource: local - /path/doc2\nContent: Content of doc 2."
        )
        self.mock_summarize.assert_called_once_with(data=expected_analysis_input)
        self.mock_keyword.assert_called_once_with(data=expected_analysis_input)

        # LLM (合成) 呼び出し確認
        self.mock_llm_client.invoke.assert_called_once()
        synthesis_call_args = self.mock_llm_client.invoke.call_args[0][0]
        # synthesis_call_args は PromptValue の可能性があるため、内容を確認
        self.assertIn(initial_state["current_query"], str(synthesis_call_args))
        self.assertIn(f"- summarize: {summary_result}", str(synthesis_call_args))
        self.assertIn(f"- keyword_extract: {keyword_result}", str(synthesis_call_args))
        self.assertIn("[web] Doc 1", str(synthesis_call_args))  # 検索結果要約の一部

        # 状態更新確認
        self.assertEqual(result_state["analysis_results"]["summarize"], summary_result)
        self.assertEqual(result_state["analysis_results"]["keyword_extract"], keyword_result)
        self.assertEqual(result_state["synthesis_result"], synthesis_report)
        self.assertIsNone(result_state["error_info"])
        self.assertFalse(result_state["replan_needed"])

    def test_analysis_synthesis_node_analysis_error(self):
        """分析メソッド実行中にエラーが発生した場合のテスト."""
        initial_state: AgentState = {
            "current_query": "test query",
            "search_results": [{"content": "doc1"}],
            "analysis_results": {},
            "synthesis_result": None,
            "initial_query": "iq",
            "search_plan": None,
            "final_check_passed": None,
            "replan_needed": False,
            "error_info": None,
            "replan_attempts": 0,
        }
        error_message = "Analysis failed"
        self.mock_summarize.side_effect = Exception(error_message)  # summarize でエラー発生
        self.mock_keyword.return_value = ["key"]  # keyword は呼ばれないはず

        # 実行
        result_state = self.node(initial_state)

        # 検証
        self.mock_summarize.assert_called_once()  # summarize は呼ばれる
        self.mock_keyword.assert_not_called()  # keyword は呼ばれない
        self.mock_llm_client.invoke.assert_not_called()  # 合成も呼ばれない

        self.assertIsInstance(result_state["error_info"], StructuredError)
        self.assertEqual(result_state["error_info"].node_name, "analysis_synthesis")
        self.assertEqual(result_state["error_info"].error_code, "SummarizeError")
        self.assertIn(error_message, result_state["error_info"].message)

    def test_analysis_synthesis_node_synthesis_error(self):
        """レポート合成中にエラーが発生した場合のテスト."""
        initial_state: AgentState = {
            "current_query": "test query",
            "search_results": [{"content": "doc1"}],
            "analysis_results": {},
            "synthesis_result": None,
            "initial_query": "iq",
            "search_plan": None,
            "final_check_passed": None,
            "replan_needed": False,
            "error_info": None,
            "replan_attempts": 0,
        }
        self.mock_summarize.return_value = "summary"
        self.mock_keyword.return_value = ["key"]
        error_message = "Synthesis LLM failed"
        self.mock_llm_client.invoke.side_effect = Exception(error_message)  # 合成でエラー

        # 実行
        result_state = self.node(initial_state)

        # 検証
        self.mock_summarize.assert_called_once()
        self.mock_keyword.assert_called_once()
        self.mock_llm_client.invoke.assert_called_once()  # 合成は呼ばれる

        self.assertIsInstance(result_state["error_info"], StructuredError)
        self.assertEqual(result_state["error_info"].node_name, "analysis_synthesis")
        self.assertEqual(result_state["error_info"].error_code, "SynthesisError")
        self.assertIn(error_message, result_state["error_info"].message)

    def test_analysis_synthesis_node_missing_input(self):
        """入力 (search_results または current_query) が欠損している場合のテスト."""
        state_no_results: AgentState = {
            "current_query": "q",
            "search_results": None,  # None の場合
            "analysis_results": {},
            "synthesis_result": None,
            "initial_query": "iq",
            "search_plan": None,
            "final_check_passed": None,
            "replan_needed": False,
            "error_info": None,
            "replan_attempts": 0,
        }
        state_no_query: AgentState = {
            "current_query": None,  # None の場合
            "search_results": [],
            "analysis_results": {},
            "synthesis_result": None,
            "initial_query": "iq",
            "search_plan": None,
            "final_check_passed": None,
            "replan_needed": False,
            "error_info": None,
            "replan_attempts": 0,
        }

        result_state_no_results = self.node(state_no_results)
        result_state_no_query = self.node(state_no_query)

        self.assertIsInstance(result_state_no_results["error_info"], StructuredError)
        self.assertEqual(result_state_no_results["error_info"].error_code, "MissingInput")
        self.assertIn("検索結果", result_state_no_results["error_info"].message)

        self.assertIsInstance(result_state_no_query["error_info"], StructuredError)
        self.assertEqual(result_state_no_query["error_info"].error_code, "MissingInput")
        self.assertIn("現在のクエリ", result_state_no_query["error_info"].message)


if __name__ == "__main__":
    unittest.main()
