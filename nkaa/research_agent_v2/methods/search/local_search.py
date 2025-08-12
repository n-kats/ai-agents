import glob
import logging
import os
from typing import Any, Dict, List

from nkaa.research_agent_v2.methods.base_method import BaseSearchMethod

# ResearchState はこのファイルでは使用されていないため、インポートは不要

logger = logging.getLogger(__name__)


class LocalSearchMethod(BaseSearchMethod):
    """
    指定されたローカルディレクトリ内のファイルを検索するメソッド。
    """

    method_name = "local_search"  # クラス変数を追加

    def __init__(self, config: Dict[str, Any]):
        """
        LocalSearchMethodを初期化する。

        Args:
            config: メソッドの設定を含む辞書。
                    'target_directory' (str): 検索対象のディレクトリパス。
                    'file_pattern' (str, optional): 検索するファイルのパターン (例: '*.txt')。デフォルトは'*.*'。
                    'encoding' (str, optional): ファイル読み込み時のエンコーディング。デフォルトは'utf-8'。
        """
        # BaseSearchMethod.__init__ は引数を取らないため修正
        super().__init__()
        self.target_directory = config.get("target_directory")
        if not self.target_directory or not os.path.isdir(self.target_directory):
            raise ValueError(
                f"無効なディレクトリが指定されました: {self.target_directory}"
            )
        self.file_pattern = config.get("file_pattern", "*.*")
        self.encoding = config.get("encoding", "utf-8")
        logger.info(
            f"LocalSearchMethod initialized. Target directory: {self.target_directory}, File pattern: {self.file_pattern}"
        )

    def execute(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
        """
        指定されたディレクトリ内のファイルを検索し、内容をリストとして返す。
        現在の実装では、クエリ文字列は使用されず、設定されたディレクトリとパターンに一致する
        全てのファイルの内容を返します。

        Args:
            query: 検索クエリ（現在未使用）。
            **kwargs: 追加の引数（現在未使用）。

        Returns:
            検索結果のリスト。各要素は {"source": "local", "path": "...", "content": "..."} 形式。
            ファイルが見つからない場合やエラーが発生した場合は空リストを返す。
        """
        logger.info(
            f"Executing local search in '{self.target_directory}' with pattern '{self.file_pattern}'. Query: '{query}' (ignored)"
        )
        # target_directory が None でないことをアサート (mypy のため)
        assert self.target_directory is not None
        search_path = os.path.join(self.target_directory, self.file_pattern)
        found_files = glob.glob(
            search_path, recursive=True
        )  # recursive=True でサブディレクトリも検索

        if not found_files:
            logger.warning(
                f"指定されたパターンに一致するファイルが見つかりませんでした: {search_path}"
            )
            return []

        results: List[Dict[str, Any]] = []
        for file_path in found_files:
            if os.path.isfile(
                file_path
            ):  # ディレクトリではなくファイルのみを対象とする
                try:
                    with open(file_path, "r", encoding=self.encoding) as f:
                        content = f.read()
                        results.append(
                            {
                                "source": "local",
                                "path": file_path,
                                "content": content,
                                "search_method": self.method_name,  # インスタンス変数ではなくクラス変数を参照
                            }
                        )
                        logger.debug(f"Successfully read file: {file_path}")
                except Exception as e:
                    logger.error(
                        f"ファイル '{file_path}' の読み込み中にエラーが発生しました: {e}"
                    )

        if not results:
            logger.warning("ファイルは存在しましたが、内容の読み込みに失敗しました。")
            return []

        logger.info(f"Local search completed. Found and read {len(results)} files.")
        return results
