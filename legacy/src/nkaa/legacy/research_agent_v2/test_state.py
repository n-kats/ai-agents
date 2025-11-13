# -*- coding: utf-8 -*-
"""research_agent_v2.state モジュールのテスト."""

import unittest

from pydantic import ValidationError  # バリデーションエラーテスト用

from nkaa.legacy.research_agent_v2.state import (  # インポートを有効化
    AgentState,
    StructuredError,
)


class TestState(unittest.TestCase):
    """state.py の AgentState と StructuredError のテストクラス."""

    def test_structured_error_creation_with_details(self):
        """StructuredError が詳細付きで正しく生成されるかのテスト."""
        details_dict = {"param1": "value1", "param2": 123}
        error = StructuredError(
            node_name="test_node",
            error_code="TestError",
            message="This is a test error.",
            details=details_dict,
        )
        self.assertEqual(error.node_name, "test_node")
        self.assertEqual(error.error_code, "TestError")
        self.assertEqual(error.message, "This is a test error.")
        self.assertEqual(error.details, details_dict)

    def test_structured_error_creation_without_details(self):
        """StructuredError が詳細なしで正しく生成されるかのテスト."""
        error = StructuredError(
            node_name="another_node",
            error_code="AnotherError",
            message="Another error message.",
            # details は省略 (デフォルトで None になるはず)
        )
        self.assertEqual(error.node_name, "another_node")
        self.assertEqual(error.error_code, "AnotherError")
        self.assertEqual(error.message, "Another error message.")
        self.assertIsNone(error.details)

    def test_structured_error_validation(self):
        """StructuredError の必須フィールドに対するバリデーションテスト."""
        with self.assertRaises(ValidationError):
            # node_name が欠けている
            StructuredError(error_code="ValidationError", message="Missing node name")
        with self.assertRaises(ValidationError):
            # error_code が欠けている
            StructuredError(node_name="validation_node", message="Missing error code")
        with self.assertRaises(ValidationError):
            # message が欠けている
            StructuredError(node_name="validation_node", error_code="ValidationError")

    def test_agent_state_structure_and_types(self):
        """AgentState (TypedDict) の構造と基本的な型が期待通りかのテスト."""
        # サンプルデータを作成
        sample_error = StructuredError(node_name="sample_node", error_code="SampleError", message="Sample")
        state: AgentState = {
            "initial_query": "initial",
            "current_query": "current",
            "search_plan": ["plan A", "plan B"],
            "search_results": [{"source": "web", "content": "result1"}],
            "analysis_results": {"summary": "summary text"},
            "synthesis_result": "final report",
            "final_check_passed": True,
            "replan_needed": False,
            "error_info": sample_error,
            "replan_attempts": 1,
        }

        # 全てのキーが存在するか確認
        expected_keys = [
            "initial_query",
            "current_query",
            "search_plan",
            "search_results",
            "analysis_results",
            "synthesis_result",
            "final_check_passed",
            "replan_needed",
            "error_info",
            "replan_attempts",
        ]
        for key in expected_keys:
            self.assertIn(key, state, f"キー '{key}' が AgentState に存在しません。")

        # 簡単な型チェック
        self.assertIsInstance(state["initial_query"], str)
        self.assertIsInstance(state["current_query"], str)
        self.assertTrue(isinstance(state["search_plan"], list) or state["search_plan"] is None)
        self.assertIsInstance(state["search_results"], list)
        self.assertIsInstance(state["analysis_results"], dict)
        self.assertTrue(isinstance(state["synthesis_result"], str) or state["synthesis_result"] is None)
        self.assertTrue(isinstance(state["final_check_passed"], bool) or state["final_check_passed"] is None)
        self.assertIsInstance(state["replan_needed"], bool)
        self.assertTrue(isinstance(state["error_info"], StructuredError) or state["error_info"] is None)
        self.assertIsInstance(state["replan_attempts"], int)

        # error_info が None の場合もテスト
        state_no_error: AgentState = {
            "initial_query": "q",
            "current_query": "q",
            "search_plan": None,
            "search_results": [],
            "analysis_results": {},
            "synthesis_result": None,
            "final_check_passed": None,
            "replan_needed": False,
            "error_info": None,  # エラーなし
            "replan_attempts": 0,
        }
        self.assertIsNone(state_no_error["error_info"])


if __name__ == "__main__":
    unittest.main()
