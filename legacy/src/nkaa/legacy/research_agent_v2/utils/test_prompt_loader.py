# -*- coding: utf-8 -*-
"""research_agent_v2.utils.prompt_loader モジュールのテスト."""

import unittest
from pathlib import Path  # Path をインポート
from unittest.mock import mock_open, patch

# jinja2 のインポートは不要になった
# インポートを有効化
from nkaa.legacy.research_agent_v2.utils.prompt_loader import load_prompt_template

# モック用の Path オブジェクト
MOCK_PROMPTS_PATH = Path("/mock/prompts/dir")


# PROMPTS_DIR を Path オブジェクトでモック (クラスデコレータとして適用)
@patch("nkaa.legacy.research_agent_v2.utils.prompt_loader.PROMPTS_DIR", new=MOCK_PROMPTS_PATH)
class TestPromptLoader(unittest.TestCase):
    """utils.prompt_loader の load_prompt_template 関数のテストクラス."""

    @patch("pathlib.Path.is_file")  # is_file をモック
    @patch("builtins.open", new_callable=mock_open, read_data="Template content")
    def test_load_prompt_template_success(self, mock_open_file, mock_is_file):
        """プロンプトテンプレートが正しく読み込まれるかのテスト."""
        mock_is_file.return_value = True  # ファイルは存在すると仮定
        template_name = "test_template.j2"
        expected_content = "Template content"

        loaded_content = load_prompt_template(template_name)

        # アサーション
        expected_path = MOCK_PROMPTS_PATH / template_name
        # is_file は Path オブジェクトのメソッドとして呼ばれる
        # Path(expected_path).is_file() のように呼ばれるため、
        # mock_is_file がアタッチされた Path インスタンスで呼ばれることを確認
        # (ここではインスタンスの特定が難しいため、呼ばれたことだけ確認)
        mock_is_file.assert_called_once()

        mock_open_file.assert_called_once_with(expected_path, "r", encoding="utf-8")
        self.assertEqual(loaded_content, expected_content)

    @patch("pathlib.Path.is_file")
    def test_load_prompt_template_not_found(self, mock_is_file):
        """テンプレートファイルが見つからない場合のテスト."""
        mock_is_file.return_value = False  # ファイルが存在しないと仮定
        template_name = "non_existent_template.j2"

        with self.assertRaises(FileNotFoundError) as cm:
            load_prompt_template(template_name)

        expected_path = MOCK_PROMPTS_PATH / template_name
        self.assertIn(
            f"プロンプトテンプレートファイルが見つかりません: {expected_path}",
            str(cm.exception),
        )
        mock_is_file.assert_called_once()

    @patch("pathlib.Path.is_file")
    @patch("builtins.open", side_effect=IOError("Read error"))
    def test_load_prompt_template_read_error(self, mock_open_file, mock_is_file):
        """ファイル読み込み中にエラーが発生した場合のテスト."""
        mock_is_file.return_value = True  # ファイルは存在すると仮定
        template_name = "error_template.j2"

        with self.assertRaises(IOError) as cm:  # 元の例外が再送出されるはず
            load_prompt_template(template_name)

        expected_path = MOCK_PROMPTS_PATH / template_name
        mock_is_file.assert_called_once()
        mock_open_file.assert_called_once_with(expected_path, "r", encoding="utf-8")
        self.assertIn("Read error", str(cm.exception))

    @patch("pathlib.Path.is_file")
    @patch("builtins.open", new_callable=mock_open, read_data="Template content")
    def test_load_prompt_template_with_extension(self, mock_open_file, mock_is_file):
        """ファイル名に既に .j2 が含まれている場合のテスト."""
        mock_is_file.return_value = True
        template_name_with_ext = "already_has.j2"
        expected_content = "Template content"

        loaded_content = load_prompt_template(template_name_with_ext)

        expected_path = MOCK_PROMPTS_PATH / template_name_with_ext  # 拡張子はそのまま
        mock_is_file.assert_called_once()
        mock_open_file.assert_called_once_with(expected_path, "r", encoding="utf-8")
        self.assertEqual(loaded_content, expected_content)


if __name__ == "__main__":
    unittest.main()
