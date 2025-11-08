import logging
import os
from typing import Any, Dict, List, Optional

from langchain_community.tools.tavily_search import TavilySearchResults

from nkaa.legacy.research_agent_v2.config.settings import WebSearchSettings
from nkaa.legacy.research_agent_v2.methods.base_method import BaseSearchMethod

logger = logging.getLogger(__name__)


class WebSearchMethod(BaseSearchMethod):
    """
    Web検索を実行するメソッド。
    現在は Tavily をサポート。
    """

    method_name = "web_search"

    def __init__(self, settings: Optional[Dict[str, Any]] = None, **kwargs: Any):
        """
        コンストラクタ。

        Args:
            settings: メソッド固有の設定 (WebSearchSettings に準拠する辞書)。
        """
        super().__init__(**kwargs)

        # 設定をパース (デフォルト値も考慮)
        method_settings = WebSearchSettings(**(settings or {}))
        self.provider = method_settings.provider.lower()
        self.num_results = method_settings.num_results
        # self.api_key は method_settings から削除されたため、初期化
        self.api_key: Optional[str] = None

        # APIキーを環境変数から取得
        if self.provider == "tavily":
            env_api_key = os.getenv("TAVILY_API_KEY")
            if env_api_key:
                self.api_key = env_api_key
        # 他のプロバイダーも同様に追加可能

        # 検索ツールを初期化
        self.search_tool = None
        if self.provider == "tavily":
            if not self.api_key:
                logger.warning(
                    f"メソッド '{self.method_name}' (Tavily): APIキーが設定されていません。環境変数 TAVILY_API_KEY を設定してください。"
                )
            else:
                try:
                    self.search_tool = TavilySearchResults(api_key=self.api_key, max_results=self.num_results)
                    logger.info(f"Tavily検索ツールを初期化しました (max_results={self.num_results})。")
                except ImportError:
                    logger.error("Tavily検索ツールを使用するには 'tavily-python' をインストールしてください。")
                    self.search_tool = None
                except Exception as e:
                    logger.error(f"Tavily検索ツールの初期化に失敗しました: {e}")
                    self.search_tool = None
        else:
            logger.error(f"サポートされていないWeb検索プロバイダーです: {self.provider}")

    def execute(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
        """
        Web検索を実行する。

        Args:
            query: 検索クエリ文字列。
            **kwargs: 追加パラメータ (現在は未使用)。

        Returns:
            検索結果のリスト。各要素は {"source": "web", "url": "...", "title": "...", "content": "..."} 形式。
            エラー発生時やツールが初期化されていない場合は空リストを返す。
        """
        if not self.search_tool:
            logger.error(f"メソッド '{self.method_name}': 検索ツールが初期化されていません。")
            return []

        logger.info(f"メソッド '{self.method_name}' ({self.provider}) を開始します。クエリ: '{query}'")

        try:
            # TavilySearchResults は結果を辞書のリストとして返す
            # [{'url': '...', 'content': '...'}, ...]
            results = self.search_tool.invoke(query)

            if not isinstance(results, list):
                logger.warning(f"Tavily検索結果が予期しない形式です ({type(results)})。空リストを返します。")
                return []

            # 結果を標準形式に整形
            formatted_results: List[Dict[str, Any]] = []
            for res in results:
                if isinstance(res, dict) and "url" in res and "content" in res:
                    formatted_results.append(
                        {
                            "source": "web",
                            "url": res.get("url"),
                            "title": res.get("title", "タイトルなし"),  # title があれば使う
                            "content": res.get("content"),
                            "search_method": self.method_name,  # どのメソッドからの結果か
                            "provider": self.provider,
                        }
                    )
                else:
                    logger.warning(f"不正な形式の検索結果をスキップ: {res}")

            logger.info(
                f"メソッド '{self.method_name}' が完了しました。{len(formatted_results)} 件の結果を取得しました。"
            )
            return formatted_results

        except Exception as e:
            logger.error(
                f"メソッド '{self.method_name}' の実行中にエラーが発生しました: {e}",
                exc_info=True,
            )
            return []  # エラー時は空リストを返す
