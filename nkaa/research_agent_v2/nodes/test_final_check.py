# -*- coding: utf-8 -*-
"""research_agent_v2.nodes.final_check モジュールのテスト."""

import unittest
from unittest.mock import MagicMock, patch

# BaseChatModel をインポート
from langchain_core.language_models import BaseChatModel

# インポートを有効化
from nkaa.research_agent_v2.nodes.final_check import FinalCheckNode
from nkaa.research_agent_v2.state import AgentState, StructuredError


class TestFinalCheckNode(unittest.TestCase):
    """nodes.final_check.FinalCheckNode のテストクラス."""

    def setUp(self):
        """テスト前のセットアップ."""
        patcher = patch(
            "nkaa.research_agent_v2.utils.prompt_loader.load_prompt_template"
        )
        self.mock_load_prompt = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_load_prompt.return_value = "チェックプロンプト: {query} {report}"
        self.mock_llm_client = MagicMock(spec=BaseChatModel)
        # FinalCheckNode のインスタンス化
        self.node = FinalCheckNode(llm_client=self.mock_llm_client)
        # 内部チェーンの invoke をモック
        self.mock_chain_invoke = MagicMock()
        # FinalCheckNode 内のチェーンオブジェクトを特定してパッチを当てるのは複雑なため、
        # execute 内で chain.invoke が呼ばれる箇所を直接パッチするアプローチも検討可能だが、
        # ここでは setUp でインスタンス化した node の chain 属性を差し替える形でモックする
        # (ただし、実際の chain オブジェクトの型と合わせる必要がある)
        # 簡単のため、execute 内の chain.invoke をテストメソッド内で patch する方式を採用する

    def _get_initial_state(self, report="report", query="query") -> AgentState:
        """テスト用の初期状態を生成するヘルパー"""
        return {
            "current_query": query,
            "synthesis_result": report,
            "final_check_passed": None,
            # 他の必須キー
            "initial_query": "iq",
            "search_plan": None,
            "search_results": [],
            "analysis_results": {},
            "replan_needed": False,
            "error_info": None,
            "replan_attempts": 0,
        }

    @patch(
        "nkaa.research_agent_v2.nodes.final_check.ChatPromptTemplate"
    )  # チェーン構築を阻止
    @patch("nkaa.research_agent_v2.nodes.final_check.BooleanOutputParser")
    def test_final_check_node_call_passed(self, mock_parser_cls, mock_prompt_cls):
        """FinalCheckNode の __call__ メソッド (チェック通過) のテスト."""
        initial_state = self._get_initial_state(
            report="Good report", query="test query"
        )
        mock_chain_invoke = MagicMock(return_value=True)  # チェック結果 True

        # execute 内の chain.invoke をモック
        with patch.object(
            self.node.llm_client, "invoke", mock_chain_invoke
        ):  # llm_client.invoke を直接モック
            # パーサーもモック (llm_client の結果をそのまま使うため)
            mock_parser_instance = MagicMock()
            mock_parser_instance.parse.return_value = True
            mock_parser_cls.return_value = mock_parser_instance
            # プロンプトもモック
            mock_prompt_instance = MagicMock()
            mock_prompt_cls.from_template.return_value = mock_prompt_instance

            # 実際のチェーン呼び出しを模倣 (プロンプト -> LLM -> パーサー)
            # このテストでは chain 全体をモックせず、LLM の結果とパーサーの結果を制御する
            # 実際には chain = prompt | llm | parser が実行される
            # ここでは llm.invoke が呼ばれ、その結果が parser.parse に渡される、という流れを模倣
            # llm.invoke の戻り値は BaseMessage なのでそれを模倣
            mock_llm_response = MagicMock()
            mock_llm_response.content = "yes"  # パーサーが True に変換する想定の文字列
            self.mock_llm_client.invoke.return_value = mock_llm_response

            result_state = self.node(initial_state)

            # 検証
            # プロンプト -> LLM の呼び出し確認
            self.mock_llm_client.invoke.assert_called_once()
            # invoke の引数が PromptValue であることを確認 (より厳密なテスト)
            # args, kwargs = self.mock_llm_client.invoke.call_args
            # self.assertIsInstance(args[0], PromptValue)
            # self.assertIn(initial_state["current_query"], args[0].to_string())
            # self.assertIn(initial_state["synthesis_result"], args[0].to_string())

            # 状態確認
            self.assertTrue(result_state["final_check_passed"])
            self.assertFalse(result_state["replan_needed"])
            self.assertIsNone(result_state["error_info"])

    @patch("nkaa.research_agent_v2.nodes.final_check.ChatPromptTemplate")
    @patch("nkaa.research_agent_v2.nodes.final_check.BooleanOutputParser")
    def test_final_check_node_call_failed(self, mock_parser_cls, mock_prompt_cls):
        """FinalCheckNode の __call__ メソッド (チェック失敗) のテスト."""
        initial_state = self._get_initial_state(report="Bad report", query="test query")
        mock_llm_response = MagicMock()
        mock_llm_response.content = "no"  # パーサーが False に変換する想定
        self.mock_llm_client.invoke.return_value = mock_llm_response
        mock_parser_instance = MagicMock()
        mock_parser_instance.parse.return_value = False
        mock_parser_cls.return_value = mock_parser_instance
        mock_prompt_cls.from_template.return_value = MagicMock()  # プロンプトモック

        result_state = self.node(initial_state)

        # 検証
        self.mock_llm_client.invoke.assert_called_once()
        self.assertFalse(result_state["final_check_passed"])
        self.assertTrue(result_state["replan_needed"])
        self.assertIsNone(result_state["error_info"])

    @patch("nkaa.research_agent_v2.nodes.final_check.ChatPromptTemplate")
    @patch("nkaa.research_agent_v2.nodes.final_check.BooleanOutputParser")
    def test_final_check_node_error_handling(self, mock_parser_cls, mock_prompt_cls):
        """LLM呼び出しでエラーが発生した場合のテスト."""
        initial_state = self._get_initial_state()
        error_message = "LLM connection error"
        self.mock_llm_client.invoke.side_effect = Exception(error_message)
        mock_prompt_cls.from_template.return_value = MagicMock()  # プロンプトモック
        # パーサーは呼ばれないはず

        result_state = self.node(initial_state)

        # 検証
        self.mock_llm_client.invoke.assert_called_once()
        self.assertFalse(result_state["final_check_passed"])  # エラー時は False
        self.assertTrue(result_state["replan_needed"])  # エラー時は再計画
        self.assertIsInstance(result_state["error_info"], StructuredError)
        self.assertEqual(result_state["error_info"].error_code, "CheckError")
        self.assertIn(error_message, result_state["error_info"].message)

    @patch("nkaa.research_agent_v2.nodes.final_check.ChatPromptTemplate")
    @patch("nkaa.research_agent_v2.nodes.final_check.BooleanOutputParser")
    def test_final_check_node_parse_error(self, mock_parser_cls, mock_prompt_cls):
        """LLM応答のパースエラー (ValueError) が発生した場合のテスト."""
        initial_state = self._get_initial_state()
        mock_llm_response = MagicMock()
        mock_llm_response.content = "maybe"  # パースできない応答
        self.mock_llm_client.invoke.return_value = mock_llm_response
        mock_parser_instance = MagicMock()
        mock_parser_instance.parse.side_effect = ValueError(
            "Cannot parse"
        )  # パースエラー
        mock_parser_cls.return_value = mock_parser_instance
        mock_prompt_cls.from_template.return_value = MagicMock()  # プロンプトモック

        result_state = self.node(initial_state)

        # 検証
        self.mock_llm_client.invoke.assert_called_once()
        mock_parser_instance.parse.assert_called_once()  # パースは試みられる
        self.assertFalse(result_state["final_check_passed"])  # パースエラー時は False
        self.assertTrue(result_state["replan_needed"])  # 再計画
        self.assertIsNone(result_state["error_info"])  # 現在の実装ではエラー記録しない

    def test_final_check_node_missing_input(self):
        """入力 (report または query) が欠損している場合のテスト."""
        # レポートなし
        state_no_report = self._get_initial_state(report=None)
        result_no_report = self.node(state_no_report)
        self.assertFalse(result_no_report["final_check_passed"])
        self.assertTrue(result_no_report["replan_needed"])
        self.assertIsNone(result_no_report["error_info"])  # エラー記録はしない

        # クエリなし
        state_no_query = self._get_initial_state(query=None)
        result_no_query = self.node(state_no_query)
        self.assertIsNone(
            result_no_query["final_check_passed"]
        )  # チェック実行前にエラー
        self.assertFalse(
            result_no_query["replan_needed"]
        )  # エラーなので再計画フラグはそのまま
        self.assertIsInstance(result_no_query["error_info"], StructuredError)
        self.assertEqual(result_no_query["error_info"].error_code, "MissingInput")


if __name__ == "__main__":
    unittest.main()
