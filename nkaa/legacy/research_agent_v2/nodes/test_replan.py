# -*- coding: utf-8 -*-
"""research_agent_v2.nodes.replan モジュールのテスト."""

import unittest
from unittest.mock import MagicMock, patch  # ANY をインポート

# BaseChatModel をインポート
from langchain_core.language_models import BaseChatModel

# インポートを有効化
from nkaa.legacy.research_agent_v2.nodes.replan import ReplanNode
from nkaa.legacy.research_agent_v2.state import AgentState, StructuredError


@patch("nkaa.legacy.research_agent_v2.utils.prompt_loader.load_prompt_template")
class TestReplanNode(unittest.TestCase):
    """nodes.replan.ReplanNode のテストクラス."""

    def setUp(self, mock_load_prompt):
        """テスト前のセットアップ."""
        mock_load_prompt.return_value = "リプランプロンプト: {initial_query} {current_query} {report}"
        self.mock_llm_client = MagicMock(spec=BaseChatModel)
        # ReplanNode のインスタンス化
        self.node = ReplanNode(llm_client=self.mock_llm_client)
        # 内部チェーンの invoke をモック
        self.mock_chain_invoke = MagicMock()
        # execute 内の chain.invoke をテストメソッド内で patch する

    def _get_initial_state(self, replan_needed=True, attempts=0) -> AgentState:
        """テスト用の初期状態を生成するヘルパー"""
        return {
            "initial_query": "original query",
            "current_query": "failed query",
            "search_results": [{"content": "old result"}],  # リセットされるか確認用
            "analysis_results": {"summary": "old summary"},  # リセットされるか確認用
            "synthesis_result": "failed report",
            "final_check_passed": False,
            "replan_needed": replan_needed,
            "error_info": None,
            "replan_attempts": attempts,
            "search_plan": ["old plan"],  # リセットされるか確認用
        }

    def test_replan_node_call_success(self, mock_load_prompt):
        """ReplanNode の __call__ メソッド (成功時) のテスト."""
        initial_state = self._get_initial_state(replan_needed=True, attempts=0)
        new_query = "refined query"
        # BaseChatModel の invoke は content 属性を持つオブジェクトを返す想定
        mock_llm_response = MagicMock()
        mock_llm_response.content = new_query
        # StrOutputParser は content をそのまま返す
        # よって、chain.invoke は最終的に文字列 new_query を返す
        mock_chain_invoke = MagicMock(return_value=new_query)

        # execute 内の chain.invoke をモック
        with patch.object(self.node.llm_client, "invoke", return_value=mock_llm_response):  # LLM の戻り値を設定
            # ここでは parser はモックせず、LLM の結果から parser が new_query を返すことを期待
            # もし parser のロジックが複雑なら parser もモックする
            # 簡単のため、chain 全体の invoke をモックする方が楽かもしれない
            # ここでは execute 内の chain.invoke を patch する
            with patch(
                "langchain_core.runnables.base.RunnableSequence.invoke",
                mock_chain_invoke,
            ):
                result_state = self.node(initial_state)

                # 検証
                mock_chain_invoke.assert_called_once_with(
                    {
                        "initial_query": initial_state["initial_query"],
                        "current_query": initial_state["current_query"],
                        "report": initial_state["synthesis_result"],
                    }
                )
                self.assertEqual(result_state["current_query"], new_query)
                # リセットされるフィールドの確認
                self.assertIsNone(result_state["search_plan"])
                self.assertEqual(result_state["search_results"], [])
                self.assertEqual(result_state["analysis_results"], {})
                self.assertIsNone(result_state["synthesis_result"])
                self.assertIsNone(result_state["final_check_passed"])
                self.assertIsNone(result_state["error_info"])
                # フラグとカウンターの確認
                self.assertFalse(result_state["replan_needed"])
                self.assertEqual(result_state["replan_attempts"], 1)  # インクリメントされている

    def test_replan_node_error_handling(self, mock_load_prompt):
        """LLM呼び出し (chain.invoke) でエラーが発生した場合のテスト."""
        initial_state = self._get_initial_state(replan_needed=True)
        error_message = "LLM Replan failed"
        mock_chain_invoke = MagicMock(side_effect=Exception(error_message))

        with patch("langchain_core.runnables.base.RunnableSequence.invoke", mock_chain_invoke):
            result_state = self.node(initial_state)

            # 検証
            mock_chain_invoke.assert_called_once()  # invoke は呼ばれる
            self.assertIsInstance(result_state["error_info"], StructuredError)
            self.assertEqual(result_state["error_info"].node_name, "replan")
            self.assertEqual(result_state["error_info"].error_code, "ReplanError")
            self.assertIn(error_message, result_state["error_info"].message)
            self.assertFalse(result_state["replan_needed"])  # エラー時は False

    def test_replan_node_skip(self, mock_load_prompt):
        """replan_needed が False の場合にスキップされるかのテスト."""
        initial_state = self._get_initial_state(replan_needed=False)
        mock_chain_invoke = MagicMock()

        with patch("langchain_core.runnables.base.RunnableSequence.invoke", mock_chain_invoke):
            result_state = self.node(initial_state)

            # 検証
            mock_chain_invoke.assert_not_called()  # invoke は呼ばれない
            # 状態が変わっていないことを確認 (比較のためコピーを使うべきだったが、ここでは主要なものを確認)
            self.assertEqual(result_state["current_query"], initial_state["current_query"])
            self.assertFalse(result_state["replan_needed"])
            self.assertIsNone(result_state["error_info"])
            self.assertEqual(result_state["replan_attempts"], initial_state["replan_attempts"])

    def test_replan_node_empty_query(self, mock_load_prompt):
        """LLM が空のクエリを返した場合のテスト."""
        initial_state = self._get_initial_state(replan_needed=True)
        empty_query = "  "  # 空白のみ
        mock_chain_invoke = MagicMock(return_value=empty_query)

        with patch("langchain_core.runnables.base.RunnableSequence.invoke", mock_chain_invoke):
            result_state = self.node(initial_state)

            # 検証
            mock_chain_invoke.assert_called_once()
            # current_query は元のままのはず
            self.assertEqual(result_state["current_query"], initial_state["current_query"])
            self.assertFalse(result_state["replan_needed"])  # 試行はしたので False
            self.assertIsNone(result_state["error_info"])
            self.assertEqual(result_state["replan_attempts"], 1)  # 試行回数は増える


if __name__ == "__main__":
    unittest.main()
