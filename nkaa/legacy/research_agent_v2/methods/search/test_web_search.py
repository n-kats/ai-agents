# -*- coding: utf-8 -*-
"""research_agent_v2.methods.search.web_search モジュールのテスト."""

import os
import unittest
from unittest.mock import MagicMock, patch

# TavilySearchResults をインポート (モック対象の特定のため)
from langchain_community.tools.tavily_search import TavilySearchResults

# インポートを有効化
from nkaa.research_agent_v2.methods.search.web_search import WebSearchMethod


class TestWebSearchMethod(unittest.TestCase):
    """methods.search.web_search.WebSearchMethod のテストクラス."""

    def setUp(self):
        """テスト前のセットアップ."""
        patcher = patch("nkaa.research_agent_v2.methods.search.web_search.TavilySearchResults")
        self.addCleanup(patcher.stop)
        self.mock_tavily_tool_cls = patcher.start()
        self.mock_tavily_tool_instance = MagicMock(spec=TavilySearchResults)
        self.mock_tavily_tool_cls.return_value = self.mock_tavily_tool_instance
        self.settings = {"provider": "tavily", "num_results": 3}
        # APIキーがセットされている場合の初期化
        with patch.dict(os.environ, {"TAVILY_API_KEY": "fake_tavily_key"}):
            self.method = WebSearchMethod(settings=self.settings)
        # 初期化時に TavilySearchResults が呼ばれたか確認
        self.mock_tavily_tool_cls.assert_called_once_with(
            api_key="fake_tavily_key", max_results=self.settings["num_results"]
        )
        self.assertEqual(self.method.search_tool, self.mock_tavily_tool_instance)

    def test_web_search_method_search_success(self):
        """WebSearchMethod の execute メソッド (成功時) のテスト."""
        test_query = "LangGraph basics"
        mock_api_results = [
            {
                "url": "http://example.com/1",
                "content": "Result 1 content",
                "title": "Result 1",
            },
            {
                "url": "http://example.com/2",
                "content": "Result 2 content",
            },  # title なしケース
        ]
        self.mock_tavily_tool_instance.invoke.return_value = mock_api_results

        results = self.method.execute(test_query)

        # アサーション
        self.mock_tavily_tool_instance.invoke.assert_called_once_with(test_query)
        self.assertEqual(len(results), 2)

        # 1件目の結果
        self.assertEqual(results[0]["source"], "web")
        self.assertEqual(results[0]["url"], "http://example.com/1")
        self.assertEqual(results[0]["title"], "Result 1")
        self.assertEqual(results[0]["content"], "Result 1 content")
        self.assertEqual(results[0]["search_method"], "web_search")
        self.assertEqual(results[0]["provider"], "tavily")

        # 2件目の結果 (title なし)
        self.assertEqual(results[1]["source"], "web")
        self.assertEqual(results[1]["url"], "http://example.com/2")
        self.assertEqual(results[1]["title"], "タイトルなし")  # デフォルト値
        self.assertEqual(results[1]["content"], "Result 2 content")

    def test_web_search_method_search_api_error(self):
        """WebSearchMethod の execute メソッド (APIエラー時) のテスト."""
        test_query = "Error query"
        self.mock_tavily_tool_instance.invoke.side_effect = Exception("API connection failed")

        results = self.method.execute(test_query)

        # アサーション
        self.mock_tavily_tool_instance.invoke.assert_called_once_with(test_query)
        self.assertEqual(results, [])  # エラー時は空リスト

    @patch.dict(os.environ, {}, clear=True)  # APIキーがない状態
    @patch("nkaa.research_agent_v2.methods.search.web_search.TavilySearchResults")
    def test_web_search_method_init_no_key(self, mock_tavily_tool_cls):
        """APIキーなしで初期化した場合のテスト."""
        settings = {"provider": "tavily", "num_results": 3}
        method = WebSearchMethod(settings=settings)

        # TavilySearchResults は呼ばれないはず
        mock_tavily_tool_cls.assert_not_called()
        self.assertIsNone(method.search_tool)

        # execute を呼んでも空リストが返る
        results = method.execute("test query")
        self.assertEqual(results, [])

    def test_web_search_method_init_import_error(self):
        """ImportError で初期化に失敗した場合のテスト."""
        settings = {"provider": "tavily", "num_results": 3}
        with patch.dict(os.environ, {"TAVILY_API_KEY": "fake_tavily_key"}):
            with patch(
                "nkaa.research_agent_v2.methods.search.web_search.TavilySearchResults",
                side_effect=ImportError("Cannot import tavily"),
            ) as mock_tavily_import_error:
                method = WebSearchMethod(settings=settings)

                # TavilySearchResults の初期化が試みられるが ImportError が発生
                mock_tavily_import_error.assert_called_once()
                self.assertIsNone(method.search_tool)

                # execute を呼んでも空リストが返る
                results = method.execute("test query")
                self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
