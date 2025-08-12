# -*- coding: utf-8 -*-
"""research_agent_v2.methods.analysis.keyword_extract モジュールのテスト."""

import unittest
from unittest.mock import MagicMock, patch

# OutputParserException をインポート

# BaseChatModel をインポート (型ヒント用)
from langchain_core.language_models import BaseChatModel

# インポートを有効化
from nkaa.research_agent_v2.methods.analysis.keyword_extract import KeywordExtractMethod


class TestKeywordExtractMethod(unittest.TestCase):
    """methods.analysis.keyword_extract.KeywordExtractMethod のテストクラス."""

    @patch(
        "nkaa.research_agent_v2.utils.prompt_loader.load_prompt_template"
    )  # プロンプト読み込みもモック
    def setUp(self, mock_load_prompt):
        """テスト前のセットアップ."""
        mock_load_prompt.return_value = 'キーワード抽出プロンプト {{ num_keywords }}: "{{ text }}"'  # ダミープロンプト
        self.mock_llm_client = MagicMock(spec=BaseChatModel)
        self.settings = {"num_keywords": 5}
        self.method = KeywordExtractMethod(
            llm_client=self.mock_llm_client, settings=self.settings
        )
        # チェーンが正しく初期化されているか確認 (オプション)
        self.assertIsNotNone(self.method.chain)

    def test_keyword_extract_method_analyze_success(self):
        """KeywordExtractMethod の analyze メソッド (成功時) のテスト."""
        test_content = "This text contains keyword1 and keyword2."
        expected_keywords = ["keyword1", "keyword2", " keyword3 "]  # パース後のリスト
        expected_cleaned_keywords = [
            "keyword1",
            "keyword2",
            "keyword3",
        ]  # strip されたリスト

        # llm_client.invoke をモックし、生の文字列を返すようにする
        # OutputParser がこれをパースすることを期待
        raw_llm_output = "keyword1, keyword2,  keyword3 "
        with patch.object(
            self.method.llm_client, "invoke", return_value=raw_llm_output
        ) as mock_invoke:
            keywords = self.method.execute(test_content)

            # アサーション
            mock_invoke.assert_called_once()  # LLMが呼ばれたことを確認
            # 呼び出し引数の詳細なチェックは複雑なため省略
            # self.method.prompt.format(...) の結果を確認する必要がある
            self.assertEqual(
                keywords, expected_cleaned_keywords
            )  # strip されパースされた結果と比較

    def test_keyword_extract_method_analyze_llm_error(self):
        """LLM呼び出し (chain.invoke) でエラーが発生した場合のテスト."""
        test_content = "Some content"
        error_message = "LLM API Error"

        # llm_client.invoke が例外を送出するように設定
        with patch.object(
            self.method.llm_client, "invoke", side_effect=Exception(error_message)
        ) as mock_invoke:
            result = self.method.execute(test_content)

            # アサーション
            mock_invoke.assert_called_once()  # LLMが呼ばれたことを確認
            self.assertIsInstance(result, str)
            self.assertTrue(
                result.startswith("エラー: キーワード抽出処理中にエラーが発生しました")
            )
            self.assertIn(error_message, result)

    def test_keyword_extract_method_analyze_parse_error(self):
        """LLMの応答が不正でパースエラーが発生した場合のテスト."""
        test_content = "Some content"
        error_message = "Failed to parse output"

        # LLMが文字列以外の型を返し、後続のパーサーがエラーを起こすケースをシミュレート
        # (execute メソッド内の try...except Exception がこれを捕捉することをテスト)
        invalid_llm_output = 123  # 文字列ではない不正な出力
        # execute メソッドが返すエラーメッセージの接頭辞
        error_message_fragment = "エラー: キーワード抽出処理中にエラーが発生しました"

        with patch.object(
            self.method.llm_client, "invoke", return_value=invalid_llm_output
        ) as mock_llm_invoke:
            result = self.method.execute(test_content)

            # アサーション
            mock_llm_invoke.assert_called_once()  # LLMが呼ばれたことを確認
            self.assertIsInstance(result, str)
            self.assertTrue(result.startswith(error_message_fragment))
            # 捕捉される例外の具体的なメッセージ内容までは確認しない
            # self.assertIn(error_message, result) # この行を削除

    def test_keyword_extract_method_analyze_empty_input(self):
        """空または空白のみの入力に対するテスト."""
        # llm_client.invoke が呼ばれないことを確認
        with patch.object(self.method.llm_client, "invoke") as mock_invoke:
            result_empty = self.method.execute("")
            result_space = self.method.execute("   ")

            self.assertEqual(result_empty, [])
            self.assertEqual(result_space, [])
            mock_invoke.assert_not_called()

    def test_keyword_extract_method_chain_initialization_failure(self):
        """チェーンの初期化に失敗した場合のテスト."""
        # setUp で初期化済みなので、一時的に chain を None にする
        original_chain = self.method.chain
        self.method.chain = None
        try:
            result = self.method.execute("Some content")
            self.assertEqual(result, "エラー: キーワード抽出チェーンが利用できません。")
        finally:
            self.method.chain = original_chain  # 元に戻す


if __name__ == "__main__":
    unittest.main()
