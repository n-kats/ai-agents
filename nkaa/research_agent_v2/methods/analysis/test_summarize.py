# -*- coding: utf-8 -*-
"""research_agent_v2.methods.analysis.summarize モジュールのテスト."""

import unittest
from unittest.mock import ANY, MagicMock, patch  # ANY をインポート

from langchain_core.documents import Document

# BaseChatModel, Document をインポート
from langchain_core.language_models import BaseChatModel

# インポートを有効化
from nkaa.research_agent_v2.methods.analysis.summarize import SummarizeMethod


class TestSummarizeMethod(unittest.TestCase):
    """methods.analysis.summarize.SummarizeMethod のテストクラス."""

    # setUp メソッドに直接デコレータを適用する
    @patch(
        "nkaa.research_agent_v2.methods.analysis.summarize.load_summarize_chain"
    )  # 外側 -> 第2引数 (mock_load_chain)
    @patch(
        "nkaa.research_agent_v2.utils.prompt_loader.load_prompt_template"
    )  # 内側 -> 第1引数 (mock_load_prompt)
    def setUp(self, mock_load_prompt, mock_load_chain):
        """テスト前のセットアップ."""
        mock_load_prompt.side_effect = (
            lambda name: f"Mock {name} content"
        )  # ダミープロンプト内容
        self.mock_llm_client = MagicMock(spec=BaseChatModel)
        self.settings = {"chunk_size": 100, "overlap": 10}  # テスト用に小さい値
        # load_summarize_chain が返すモックチェーンを設定
        self.mock_summarize_chain = MagicMock()
        mock_load_chain.return_value = self.mock_summarize_chain

        self.method = SummarizeMethod(
            llm_client=self.mock_llm_client, settings=self.settings
        )
        # チェーンが正しく初期化されているか確認
        self.assertEqual(self.method.summarize_chain, self.mock_summarize_chain)
        # load_summarize_chain が呼ばれたか確認
        mock_load_chain.assert_called_once_with(
            llm=self.mock_llm_client,
            chain_type="map_reduce",
            map_prompt=ANY,  # PromptTemplate オブジェクト
            combine_prompt=ANY,  # PromptTemplate オブジェクト
            verbose=False,
        )

    def test_summarize_method_analyze_short_content(self):
        """SummarizeMethod の analyze メソッド (短いコンテンツ) のテスト."""
        short_content = "This is a short text, less than chunk size."
        expected_summary = "short summary"
        self.mock_summarize_chain.invoke.return_value = {
            "output_text": expected_summary
        }

        summary = self.method.execute(short_content)

        # アサーション
        # invoke が呼ばれたか、引数を確認
        self.mock_summarize_chain.invoke.assert_called_once()
        call_args = self.mock_summarize_chain.invoke.call_args[0][0]
        self.assertIn("input_documents", call_args)
        self.assertEqual(len(call_args["input_documents"]), 1)  # 1チャンクのはず
        self.assertIsInstance(call_args["input_documents"][0], Document)
        self.assertEqual(call_args["input_documents"][0].page_content, short_content)
        # 結果の確認
        self.assertEqual(summary, expected_summary)

    def test_summarize_method_analyze_long_content(self):
        """SummarizeMethod の analyze メソッド (長いコンテンツ) のテスト."""
        # chunk_size=100, overlap=10 なので、200文字あれば複数チャンクになるはず
        long_content = ("This is a long text. " * 15) + "End."
        expected_summary = "long combined summary"
        self.mock_summarize_chain.invoke.return_value = {
            "output_text": expected_summary
        }

        summary = self.method.execute(long_content)

        # アサーション
        self.mock_summarize_chain.invoke.assert_called_once()
        call_args = self.mock_summarize_chain.invoke.call_args[0][0]
        self.assertIn("input_documents", call_args)
        self.assertGreater(len(call_args["input_documents"]), 1)  # 複数チャンクのはず
        self.assertIsInstance(call_args["input_documents"][0], Document)
        # 結果の確認
        self.assertEqual(summary, expected_summary)

    def test_summarize_method_analyze_error_handling(self):
        """LLM呼び出し (summarize_chain.invoke) でエラーが発生した場合のテスト."""
        test_content = "Some content"
        error_message = "LLM API Error"
        self.mock_summarize_chain.invoke.side_effect = Exception(error_message)

        result = self.method.execute(test_content)

        # アサーション
        self.mock_summarize_chain.invoke.assert_called_once()  # invoke は呼ばれる
        self.assertIsInstance(result, str)
        self.assertTrue(result.startswith("エラー: 要約処理中にエラーが発生しました"))
        self.assertIn(error_message, result)

    def test_summarize_method_analyze_empty_input(self):
        """空または空白のみの入力に対するテスト."""
        result_empty = self.method.execute("")
        result_space = self.method.execute("   ")

        self.assertEqual(result_empty, "(要約対象データなし)")
        self.assertEqual(result_space, "(要約対象データなし)")
        self.mock_summarize_chain.invoke.assert_not_called()

    def test_summarize_method_chain_initialization_failure(self):
        """チェーンの初期化に失敗した場合のテスト."""
        # setUp で初期化済みなので、一時的に chain を None にする
        original_chain = self.method.summarize_chain
        self.method.summarize_chain = None
        try:
            result = self.method.execute("Some content")
            self.assertEqual(result, "エラー: 要約チェーンが利用できません。")
        finally:
            self.method.summarize_chain = original_chain  # 元に戻す


if __name__ == "__main__":
    unittest.main()
