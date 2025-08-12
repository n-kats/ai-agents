# -*- coding: utf-8 -*-
"""research_agent_v2.methods.search.local_search モジュールのテスト."""

import os
import unittest
from unittest.mock import call, mock_open, patch  # call をインポート

# インポートを有効化
from nkaa.research_agent_v2.methods.search.local_search import LocalSearchMethod


class TestLocalSearchMethod(unittest.TestCase):
    """methods.search.local_search.LocalSearchMethod のテストクラス."""

    def setUp(self):
        """テスト前のセットアップ."""
        # os.path.isdir をpatcherでモック
        patcher = patch("os.path.isdir")
        self.addCleanup(patcher.stop)
        self.mock_isdir = patcher.start()
        self.mock_isdir.return_value = True  # ディレクトリは存在すると仮定
        self.test_dir = "/mock/search/dir"
        self.file_pattern = "*.md"
        self.encoding = "utf-16"  # デフォルト以外をテスト
        self.config = {
            "target_directory": self.test_dir,
            "file_pattern": self.file_pattern,
            "encoding": self.encoding,
        }
        # LocalSearchMethod は config を受け取る
        self.method = LocalSearchMethod(config=self.config)

    @patch("glob.glob")
    @patch("os.path.isfile")
    @patch("builtins.open", new_callable=mock_open, read_data="Mock file content")
    def test_local_search_method_search_success(
        self, mock_open_file, mock_isfile, mock_glob
    ):
        """LocalSearchMethod の execute メソッド (成功時) のテスト."""
        mock_file_paths = [
            os.path.join(self.test_dir, "file1.md"),
            os.path.join(self.test_dir, "subdir", "file2.md"),
            os.path.join(self.test_dir, "ignored.txt"),  # パターンに一致しない
            os.path.join(self.test_dir, "also_ignored_dir"),  # isfile=False
        ]
        # glob はパターンに一致するファイルのみ返す想定
        mock_glob.return_value = [mock_file_paths[0], mock_file_paths[1]]
        # isfile は glob が返したパスに対して True を返す
        mock_isfile.side_effect = lambda path: path in mock_glob.return_value

        results = self.method.execute("dummy query")

        # アサーション
        expected_glob_path = os.path.join(self.test_dir, self.file_pattern)
        mock_glob.assert_called_once_with(expected_glob_path, recursive=True)
        # isfile が呼ばれたか確認
        mock_isfile.assert_has_calls(
            [call(mock_file_paths[0]), call(mock_file_paths[1])]
        )
        # open が呼ばれたか確認
        mock_open_file.assert_has_calls(
            [
                call(mock_file_paths[0], "r", encoding=self.encoding),
                call(mock_file_paths[1], "r", encoding=self.encoding),
            ],
            any_order=True,  # 順序は問わない
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["source"], "local")
        self.assertEqual(results[0]["path"], mock_file_paths[0])
        self.assertEqual(results[0]["content"], "Mock file content")
        self.assertEqual(results[0]["search_method"], "local_search")
        self.assertEqual(results[1]["path"], mock_file_paths[1])

    @patch("os.path.isdir")
    def test_local_search_method_init_dir_not_found(self, mock_isdir):
        """LocalSearchMethod の初期化 (ディレクトリ不存在時) のテスト."""
        mock_isdir.return_value = False  # ディレクトリが存在しないと仮定
        invalid_config = {"target_directory": "/invalid/path"}
        with self.assertRaises(ValueError) as cm:
            LocalSearchMethod(config=invalid_config)
        self.assertIn("無効なディレクトリが指定されました", str(cm.exception))

    @patch("glob.glob")
    def test_local_search_method_search_no_files_found(self, mock_glob):
        """LocalSearchMethod の execute メソッド (ファイルが見つからない場合) のテスト."""
        mock_glob.return_value = []  # 空リストを返す

        results = self.method.execute("dummy query")

        expected_glob_path = os.path.join(self.test_dir, self.file_pattern)
        mock_glob.assert_called_once_with(expected_glob_path, recursive=True)
        self.assertEqual(results, [])

    @patch("glob.glob")
    @patch("os.path.isfile")
    @patch("builtins.open", side_effect=IOError("Permission denied"))
    def test_local_search_method_search_file_read_error(
        self, mock_open_file, mock_isfile, mock_glob
    ):
        """LocalSearchMethod の execute メソッド (ファイル読み込みエラー時) のテスト."""
        mock_file_path = os.path.join(self.test_dir, "error.md")
        mock_glob.return_value = [mock_file_path]
        mock_isfile.return_value = True

        results = self.method.execute("dummy query")

        expected_glob_path = os.path.join(self.test_dir, self.file_pattern)
        mock_glob.assert_called_once_with(expected_glob_path, recursive=True)
        mock_isfile.assert_called_once_with(mock_file_path)
        mock_open_file.assert_called_once_with(
            mock_file_path, "r", encoding=self.encoding
        )
        self.assertEqual(results, [])  # エラーファイルは結果に含まれない


if __name__ == "__main__":
    unittest.main()
