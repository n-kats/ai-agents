# -*- coding: utf-8 -*-
"""research_agent_v2.nodes.base_node モジュールのテスト."""

import unittest
from unittest.mock import patch

# インポートを有効化
from nkaa.research_agent_v2.nodes.base_node import BaseNode
from nkaa.research_agent_v2.state import AgentState, StructuredError


# --- テスト用具象クラス ---
class ConcreteNode(BaseNode):
    node_name = "concrete_node"  # クラス変数 node_name を定義

    # __init__ は BaseNode のものをそのまま使う

    def execute(self, state: AgentState) -> AgentState:
        # ダミーの実装 (テスト内でモックされることが多い)
        state["current_query"] = state.get("current_query", "") + "_processed"
        return state


class NodeWithoutName(BaseNode):
    # node_name を定義しないクラス
    def execute(self, state: AgentState) -> AgentState:
        return state


class TestBaseNodeMethods(unittest.TestCase):
    """nodes.base_node.BaseNode のメソッドテストクラス."""

    def test_base_node_initialization(self):
        """BaseNode の初期化 (node_name チェック) テスト."""
        # node_name がないとエラー
        with self.assertRaises(NotImplementedError) as cm:
            NodeWithoutName()
        self.assertIn("'node_name' を定義する必要があります", str(cm.exception))

        # node_name があれば成功
        try:
            node = ConcreteNode()
            self.assertEqual(node.node_name, "concrete_node")
        except Exception as e:
            self.fail(f"ConcreteNode の初期化に失敗しました: {e}")

    def test_base_node_call_success(self):
        """BaseNode の __call__ が execute を呼び出し、エラー情報をクリアするかのテスト."""
        node = ConcreteNode()
        initial_state: AgentState = {
            "current_query": "initial",
            "error_info": StructuredError(
                node_name="prev", error_code="PrevError", message="Previous error"
            ),
            # 他の必須キーも設定
            "initial_query": "iq",
            "search_plan": None,
            "search_results": [],
            "analysis_results": {},
            "synthesis_result": None,
            "final_check_passed": None,
            "replan_needed": False,
            "replan_attempts": 0,
        }
        # execute が返す状態を定義
        expected_state_after_execute = initial_state.copy()
        expected_state_after_execute["current_query"] = "initial_processed"
        expected_state_after_execute["error_info"] = (
            None  # execute 内でエラーがなければ None のはず
        )

        # node.execute をモック
        with patch.object(
            node, "execute", return_value=expected_state_after_execute
        ) as mock_execute:
            result_state = node(initial_state.copy())  # コピーを渡す

            # 検証
            # execute が呼ばれる前に error_info が None になっていることを確認するのは難しいが、
            # execute が正しい引数で呼ばれ、その結果が返ることを確認する
            mock_execute.assert_called_once()
            call_args_state = mock_execute.call_args[0][0]
            self.assertIsNone(
                call_args_state.get("error_info")
            )  # execute に渡る state では error_info がクリアされているはず
            self.assertEqual(
                call_args_state["current_query"], "initial"
            )  # 元の state が渡されている

            # 最終的な結果が execute の戻り値と同じか確認
            self.assertEqual(result_state, expected_state_after_execute)

    def test_base_node_call_error(self):
        """BaseNode の __call__ が execute 中のエラーを捕捉し、_handle_error を呼ぶかのテスト."""
        node = ConcreteNode()
        initial_state: AgentState = {
            "current_query": "initial",
            "error_info": None,
            # 他の必須キー
            "initial_query": "iq",
            "search_plan": None,
            "search_results": [],
            "analysis_results": {},
            "synthesis_result": None,
            "final_check_passed": None,
            "replan_needed": False,
            "replan_attempts": 0,
        }
        error_message = "Execution failed"

        # node.execute が例外を送出するようにモック
        with patch.object(
            node, "execute", side_effect=Exception(error_message)
        ) as mock_execute:
            result_state = node(initial_state.copy())  # コピーを渡す

            # 検証
            mock_execute.assert_called_once()  # execute は呼ばれる

            # error_info が設定されているか確認
            self.assertIsInstance(result_state["error_info"], StructuredError)
            self.assertEqual(result_state["error_info"].node_name, node.node_name)
            self.assertEqual(result_state["error_info"].error_code, "UnhandledError")
            self.assertIn(error_message, result_state["error_info"].message)

    def test_base_node_handle_error(self):
        """BaseNode の _handle_error が正しく state を更新するかのテスト."""
        node = ConcreteNode()
        initial_state: AgentState = {
            "current_query": "initial",
            "error_info": None,
            # 他の必須キー
            "initial_query": "iq",
            "search_plan": None,
            "search_results": [],
            "analysis_results": {},
            "synthesis_result": None,
            "final_check_passed": None,
            "replan_needed": False,
            "replan_attempts": 0,
        }
        error_code = "SpecificError"
        message = "A specific error occurred."
        details = {"detail_key": "detail_value"}
        exception_obj = ValueError("Original exception")

        # _handle_error を直接呼び出し
        result_state = node._handle_error(
            initial_state.copy(),  # コピーを渡す
            error_code=error_code,
            message=message,
            details=details,
            exception=exception_obj,
        )

        # 検証
        self.assertIsInstance(result_state["error_info"], StructuredError)
        self.assertEqual(result_state["error_info"].node_name, node.node_name)
        self.assertEqual(result_state["error_info"].error_code, error_code)
        self.assertEqual(result_state["error_info"].message, message)
        self.assertEqual(result_state["error_info"].details, details)


if __name__ == "__main__":
    unittest.main()
