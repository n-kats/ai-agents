import logging

# Optional, List をインポート
from typing import Any, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import CommaSeparatedListOutputParser
from langchain_core.prompts import PromptTemplate

# RunnableSerializable をインポート
from langchain_core.runnables import RunnableSerializable

from nkaa.legacy.research_agent_v2.config.settings import KeywordExtractSettings
from nkaa.legacy.research_agent_v2.methods.base_method import BaseAnalysisMethod
from nkaa.legacy.research_agent_v2.utils.prompt_loader import load_prompt_template

logger = logging.getLogger(__name__)

DEFAULT_KEYWORD_EXTRACT_PROMPT_NAME = "keyword_extract_prompt"


class KeywordExtractMethod(BaseAnalysisMethod):
    """
    テキストデータからキーワードを抽出する分析メソッド。
    """

    method_name = "keyword_extract"

    def __init__(
        self,
        llm_client: BaseChatModel,
        settings: Optional[Dict[str, Any]] = None,
        prompt_name: str = DEFAULT_KEYWORD_EXTRACT_PROMPT_NAME,
        **kwargs: Any,
    ):
        """
        コンストラクタ。

        Args:
            llm_client: キーワード抽出に使用するLLMクライアント。
            settings: メソッド固有の設定 (KeywordExtractSettings に準拠する辞書)。
            prompt_name: 使用するプロンプト名。
        """
        super().__init__(**kwargs)
        self.llm_client = llm_client

        # 設定をパース
        method_settings = KeywordExtractSettings(**(settings or {}))
        self.num_keywords = method_settings.num_keywords

        # プロンプトテンプレートをロード
        try:
            prompt_template_str = load_prompt_template(prompt_name)
            self.prompt = PromptTemplate.from_template(prompt_template_str)
        except Exception as e:
            logger.error(f"キーワード抽出プロンプト '{prompt_name}.j2' の読み込みに失敗: {e}。デフォルトを使用します。")
            self.prompt = PromptTemplate.from_template(
                '以下のテキストから、内容を最もよく表す重要なキーワードを {{ num_keywords }} 個抽出してください。\nキーワードは名詞または複合名詞が望ましいです。\n結果はカンマ区切りのリスト形式で出力してください。\n\nテキスト:\n"{text}"\n\nキーワード (カンマ区切り):'
            )

        self.output_parser = CommaSeparatedListOutputParser()

        # チェーンを初期化 (型ヒントを追加)
        self.chain: Optional[RunnableSerializable[Dict[str, Any], List[str]]] = None
        try:
            self.chain = self.prompt | self.llm_client | self.output_parser
            logger.info(f"キーワード抽出チェーン ({prompt_name}) を初期化しました。")
        except Exception as e:
            logger.error(f"キーワード抽出チェーンの初期化に失敗しました: {e}", exc_info=True)
            self.chain = None

    def execute(self, data: Any, **kwargs: Any) -> Any:
        """
        入力テキストデータからキーワードを抽出する。

        Args:
            data: キーワード抽出対象のテキスト文字列。
            **kwargs: 追加パラメータ (現在は未使用)。

        Returns:
            抽出されたキーワードのリスト (List[str])。エラー時はエラーメッセージ文字列。
        """
        if not isinstance(data, str):
            logger.error(f"メソッド '{self.method_name}' は文字列入力を期待しますが、'{type(data)}' を受け取りました。")
            return "エラー: 入力データは文字列である必要があります。"
        if not data.strip():
            logger.warning(f"メソッド '{self.method_name}': 空の入力データを受け取りました。")
            return []  # 空のリストを返す
        if not self.chain:
            logger.error(f"メソッド '{self.method_name}': キーワード抽出チェーンが初期化されていません。")
            return "エラー: キーワード抽出チェーンが利用できません。"

        logger.info(f"メソッド '{self.method_name}' を開始します。入力データ長: {len(data)}文字")

        try:
            # チェーンを実行
            keywords = self.chain.invoke({"text": data, "num_keywords": self.num_keywords})

            if not isinstance(keywords, list):
                logger.warning(f"キーワード抽出結果がリストではありませんでした: {keywords}。空リストを返します。")
                return []

            # 空文字列などを除去
            cleaned_keywords = [kw.strip() for kw in keywords if kw.strip()]

            logger.info(f"メソッド '{self.method_name}' が完了しました。抽出キーワード数: {len(cleaned_keywords)}")
            return cleaned_keywords

        except Exception as e:
            logger.error(
                f"メソッド '{self.method_name}' の実行中にエラーが発生しました: {e}",
                exc_info=True,
            )
            return f"エラー: キーワード抽出処理中にエラーが発生しました - {e}"
