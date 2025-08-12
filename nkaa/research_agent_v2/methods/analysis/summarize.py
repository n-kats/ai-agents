import logging

# Optional をインポート
from typing import Any, Dict, Optional

# BaseCombineDocumentsChain をインポート
from langchain.chains.combine_documents.base import BaseCombineDocumentsChain
from langchain.chains.summarize import load_summarize_chain

# Document をインポート
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import PromptTemplate
from langchain_text_splitters import RecursiveCharacterTextSplitter

from nkaa.research_agent_v2.config.settings import SummarizeSettings
from nkaa.research_agent_v2.methods.base_method import BaseAnalysisMethod
from nkaa.research_agent_v2.utils.prompt_loader import load_prompt_template

logger = logging.getLogger(__name__)

DEFAULT_MAP_PROMPT_NAME = "summarize_map_prompt"
DEFAULT_COMBINE_PROMPT_NAME = "summarize_combine_prompt"


class SummarizeMethod(BaseAnalysisMethod):
    """
    テキストデータを要約する分析メソッド。
    LangChain の MapReduce 要約チェーンを利用する。
    """

    method_name = "summarize"

    def __init__(
        self,
        llm_client: BaseChatModel,
        settings: Optional[Dict[str, Any]] = None,
        map_prompt_name: str = DEFAULT_MAP_PROMPT_NAME,
        combine_prompt_name: str = DEFAULT_COMBINE_PROMPT_NAME,
        **kwargs: Any,
    ):
        """
        コンストラクタ。

        Args:
            llm_client: 要約に使用するLLMクライアント。
            settings: メソッド固有の設定 (SummarizeSettings に準拠する辞書)。
            map_prompt_name: Mapステップで使用するプロンプト名。
            combine_prompt_name: Combineステップで使用するプロンプト名。
        """
        super().__init__(**kwargs)
        self.llm_client = llm_client

        # 設定をパース (デフォルト値も考慮)
        method_settings = SummarizeSettings(**(settings or {}))
        self.chunk_size = method_settings.chunk_size
        self.overlap = method_settings.overlap

        # プロンプトテンプレートをロード
        try:
            map_template_str = load_prompt_template(map_prompt_name)
            self.map_prompt = PromptTemplate.from_template(map_template_str)
        except Exception as e:
            logger.error(
                f"Mapプロンプト '{map_prompt_name}.j2' の読み込みに失敗: {e}。デフォルトを使用します。"
            )
            self.map_prompt = PromptTemplate.from_template(
                '以下のテキストチャンクの要点を簡潔にまとめてください。\n\nテキスト:\n"{text}"\n\n簡潔な要約:'
            )

        try:
            combine_template_str = load_prompt_template(combine_prompt_name)
            self.combine_prompt = PromptTemplate.from_template(combine_template_str)
        except Exception as e:
            logger.error(
                f"Combineプロンプト '{combine_prompt_name}.j2' の読み込みに失敗: {e}。デフォルトを使用します。"
            )
            self.combine_prompt = PromptTemplate.from_template(
                '以下に複数のテキストチャンクの要約があります。これらの要約を統合し、全体の内容を網羅した最終的な要約を作成してください。\n\n要約リスト:\n"{text}"\n\n統合された最終的な要約:'
            )

        # テキスト分割器
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size, chunk_overlap=self.overlap
        )

        # 要約チェーンを初期化 (型ヒントを追加)
        self.summarize_chain: Optional[BaseCombineDocumentsChain] = None
        try:
            self.summarize_chain = load_summarize_chain(
                llm=self.llm_client,
                chain_type="map_reduce",
                map_prompt=self.map_prompt,
                combine_prompt=self.combine_prompt,
                # document_variable_name="text", # デフォルトに任せてみる
                verbose=False,  # 必要に応じて True に変更
            )
            logger.info(
                f"MapReduce要約チェーン ({map_prompt_name}, {combine_prompt_name}) を初期化しました。"
            )
        except Exception as e:
            logger.error(f"要約チェーンの初期化に失敗しました: {e}", exc_info=True)
            self.summarize_chain = None

    def execute(self, data: Any, **kwargs: Any) -> Any:
        """
        入力テキストデータを要約する。

        Args:
            data: 要約対象のテキスト文字列。
            **kwargs: 追加パラメータ (現在は未使用)。

        Returns:
            要約されたテキスト文字列。エラー時はエラーメッセージ文字列。
        """
        if not isinstance(data, str):
            logger.error(
                f"メソッド '{self.method_name}' は文字列入力を期待しますが、'{type(data)}' を受け取りました。"
            )
            return "エラー: 入力データは文字列である必要があります。"
        if not data.strip():
            logger.warning(
                f"メソッド '{self.method_name}': 空の入力データを受け取りました。"
            )
            return "(要約対象データなし)"
        if not self.summarize_chain:
            logger.error(
                f"メソッド '{self.method_name}': 要約チェーンが初期化されていません。"
            )
            return "エラー: 要約チェーンが利用できません。"

        logger.info(
            f"メソッド '{self.method_name}' を開始します。入力データ長: {len(data)}文字"
        )

        try:
            # テキストを Document オブジェクトに分割
            docs = self.text_splitter.create_documents([data])
            logger.info(f"{len(docs)} 個のドキュメントチャンクに分割しました。")

            # 要約チェーンを実行 (入力形式を修正)
            summary = self.summarize_chain.invoke({"input_documents": docs})

            # LangChain v0.1+ では結果が辞書で返る場合がある
            if isinstance(summary, dict) and "output_text" in summary:
                result_text = summary["output_text"]
            elif isinstance(summary, str):
                result_text = summary
            else:
                logger.error(f"予期しない要約結果の型: {type(summary)}")
                return "エラー: 予期しない要約結果の型です。"

            logger.info(
                f"メソッド '{self.method_name}' が完了しました。要約長: {len(result_text)}文字"
            )
            return result_text.strip()

        except Exception as e:
            logger.error(
                f"メソッド '{self.method_name}' の実行中にエラーが発生しました: {e}",
                exc_info=True,
            )
            return f"エラー: 要約処理中にエラーが発生しました - {e}"
