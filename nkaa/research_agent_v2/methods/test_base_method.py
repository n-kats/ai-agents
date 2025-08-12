# -*- coding: utf-8 -*-
"""research_agent_v2.methods.base_method モジュールのテスト."""

import unittest

# from nkaa.research_agent_v2.methods.base_method import BaseSearchMethod, BaseAnalysisMethod # 必要に応じてインポート


# テスト用の具象クラス (BaseSearchMethod が抽象クラスの場合)
class ConcreteSearchMethod:  # BaseSearchMethod を継承
    def __init__(self, params: dict):
        self.params = params

    def search(self, query: str, **kwargs) -> list[dict]:
        # ダミーの実装
        return [{"source": "concrete_search", "query": query, "params": self.params}]


# テスト用の具象クラス (BaseAnalysisMethod が抽象クラスの場合)
class ConcreteAnalysisMethod:  # BaseAnalysisMethod を継承
    def __init__(self, params: dict):
        self.params = params

    def analyze(self, content: str, **kwargs) -> any:
        # ダミーの実装
        return {
            "method": "concrete_analysis",
            "content_length": len(content),
            "params": self.params,
        }


class TestBaseMethod(unittest.TestCase):
    """methods.base_method の基底クラスのテストクラス."""

    def test_base_search_method_interface(self):
        """BaseSearchMethod (またはその具象クラス) のインターフェーステスト."""
        # 基底クラスが Protocol や ABC でインターフェースを定義している場合、
        # 具象クラスがそのインターフェースを実装しているかを確認する
        # TODO: テストを実装する
        # 例:
        # method = ConcreteSearchMethod(params={"key": "value"})
        # result = method.search("test query", option="abc")
        # self.assertIsInstance(result, list)
        # self.assertIsInstance(result[0], dict)
        # self.assertEqual(result[0]["source"], "concrete_search")
        # # 抽象メソッドの存在確認 (ABCの場合)
        # self.assertTrue(hasattr(BaseSearchMethod, 'search'))
        # self.assertTrue(callable(getattr(BaseSearchMethod, 'search')))
        pass  # 実装待ち

    def test_base_analysis_method_interface(self):
        """BaseAnalysisMethod (またはその具象クラス) のインターフェーステスト."""
        # TODO: テストを実装する
        # 例:
        # method = ConcreteAnalysisMethod(params={"threshold": 0.5})
        # result = method.analyze("This is test content.", context="xyz")
        # self.assertIsInstance(result, dict) # または analyze の戻り値型に合わせる
        # self.assertEqual(result["method"], "concrete_analysis")
        # # 抽象メソッドの存在確認 (ABCの場合)
        # self.assertTrue(hasattr(BaseAnalysisMethod, 'analyze'))
        # self.assertTrue(callable(getattr(BaseAnalysisMethod, 'analyze')))
        pass  # 実装待ち


if __name__ == "__main__":
    unittest.main()
