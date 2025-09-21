# -*- coding: utf-8 -*-
"""research_agent_v2.graph モジュールのテスト."""

import unittest
from unittest.mock import MagicMock

from langgraph.graph import END, StateGraph

from nkaa.research_agent_v2.config.settings import Settings  # Settings をインポート

# インポートを有効化
from nkaa.research_agent_v2.graph import build_graph, create_should_replan_condition
from nkaa.research_agent_v2.nodes.analysis_synthesis import AnalysisSynthesisNode

# ノードクラスもインポート (型ヒントや node_name 参照用)
from nkaa.research_agent_v2.nodes.data_gathering import DataGatheringNode
from nkaa.research_agent_v2.nodes.final_check import FinalCheckNode
from nkaa.research_agent_v2.nodes.replan import ReplanNode
from nkaa.research_agent_v2.state import AgentState, StructuredError


class TestGraphBuilding(unittest.TestCase):
    """graph.py の build_graph 関数のテストクラス."""

    def setUp(self):
        """テスト前のセットアップ."""
        # モックノードの作成
        self.mock_data_gathering = MagicMock(spec=DataGatheringNode)
        self.mock_data_gathering.node_name = "data_gathering"
        self.mock_analysis_synthesis = MagicMock(spec=AnalysisSynthesisNode)
        self.mock_analysis_synthesis.node_name = "analysis_synthesis"
        self.mock_final_check = MagicMock(spec=FinalCheckNode)
        self.mock_final_check.node_name = "final_check"
        self.mock_replan = MagicMock(spec=ReplanNode)
        self.mock_replan.node_name = "replan"
        # モック設定の作成
        self.mock_settings = MagicMock(spec=Settings)
        self.mock_settings.max_replan_attempts = 2  # テスト用に設定

    def test_build_graph_structure(self):
        """グラフのノード、エントリーポイント、通常のエッジが正しく構築されるかのテスト."""
        graph = build_graph(
            data_gathering_node=self.mock_data_gathering,
            analysis_synthesis_node=self.mock_analysis_synthesis,
            final_check_node=self.mock_final_check,
            replan_node=self.mock_replan,
            settings=self.mock_settings,
        )

        self.assertIsInstance(graph, StateGraph)

        # ノードの存在確認
        self.assertIn(self.mock_data_gathering.node_name, graph.nodes)
        self.assertIn(self.mock_analysis_synthesis.node_name, graph.nodes)
        self.assertIn(self.mock_final_check.node_name, graph.nodes)
        self.assertIn(self.mock_replan.node_name, graph.nodes)

        # エントリーポイントの確認 (entry_point に戻す)
        self.assertEqual(graph.entry_point, self.mock_data_gathering.node_name)

        # 通常のエッジの確認
        expected_edges = {
            (
                self.mock_data_gathering.node_name,
                self.mock_analysis_synthesis.node_name,
            ),
            (self.mock_analysis_synthesis.node_name, self.mock_final_check.node_name),
            (self.mock_replan.node_name, self.mock_data_gathering.node_name),
        }
        # graph.edges は frozenset を含む set なので、比較のために変換
        actual_edges = set((edge.source, edge.target) for edge in graph.edges)
        self.assertEqual(actual_edges, expected_edges)

    def test_build_graph_conditional_edge_setup(self):
        """条件付きエッジが final_check ノードから設定されているかのテスト."""
        graph = build_graph(
            data_gathering_node=self.mock_data_gathering,
            analysis_synthesis_node=self.mock_analysis_synthesis,
            final_check_node=self.mock_final_check,
            replan_node=self.mock_replan,
            settings=self.mock_settings,
        )
        # 条件分岐の確認
        self.assertIn(self.mock_final_check.node_name, graph.branches)
        branch_info = graph.branches[self.mock_final_check.node_name]
        # branch_info はタプルのはず (condition, mapping)
        self.assertIsInstance(branch_info, tuple)
        self.assertEqual(len(branch_info), 2)
        # 条件分岐関数と行き先マップを確認 (インデックスアクセスに変更)
        condition_func = branch_info[0]
        ends_map = branch_info[1]
        self.assertTrue(callable(condition_func))
        self.assertIn("replan", ends_map)
        self.assertEqual(ends_map["replan"], self.mock_replan.node_name)
        self.assertIn("finish", ends_map)
        self.assertEqual(ends_map["finish"], END)

    def test_should_replan_condition_logic(self):
        """create_should_replan_condition が生成する関数のロジックテスト."""
        should_replan_func = create_should_replan_condition(self.mock_settings)

        # ケース1: エラーあり -> finish
        state_with_error: AgentState = {
            "error_info": StructuredError(node_name="test", error_code="Test", message="test")
        }  # type: ignore
        self.assertEqual(should_replan_func(state_with_error), "finish")

        # ケース2: 再計画必要、試行回数 < max -> replan
        state_needs_replan_ok: AgentState = {
            "replan_needed": True,
            "replan_attempts": 0,
            "error_info": None,
        }  # type: ignore
        self.assertEqual(should_replan_func(state_needs_replan_ok), "replan")
        state_needs_replan_ok_1: AgentState = {
            "replan_needed": True,
            "replan_attempts": 1,
            "error_info": None,
        }  # type: ignore
        self.assertEqual(should_replan_func(state_needs_replan_ok_1), "replan")

        # ケース3: 再計画必要、試行回数 >= max -> finish
        state_needs_replan_limit: AgentState = {
            "replan_needed": True,
            "replan_attempts": 2,
            "error_info": None,
        }  # type: ignore
        self.assertEqual(should_replan_func(state_needs_replan_limit), "finish")
        state_needs_replan_over: AgentState = {
            "replan_needed": True,
            "replan_attempts": 3,
            "error_info": None,
        }  # type: ignore
        self.assertEqual(should_replan_func(state_needs_replan_over), "finish")

        # ケース4: 再計画不要 -> finish
        state_no_replan: AgentState = {
            "replan_needed": False,
            "replan_attempts": 0,
            "error_info": None,
        }  # type: ignore
        self.assertEqual(should_replan_func(state_no_replan), "finish")

        # ケース5: replan_needed が None や未定義の場合 (False 扱い) -> finish
        state_replan_none: AgentState = {
            "replan_needed": None,
            "replan_attempts": 0,
            "error_info": None,
        }  # type: ignore
        self.assertEqual(should_replan_func(state_replan_none), "finish")
        state_replan_missing: AgentState = {"replan_attempts": 0, "error_info": None}  # type: ignore
        self.assertEqual(should_replan_func(state_replan_missing), "finish")


if __name__ == "__main__":
    unittest.main()
