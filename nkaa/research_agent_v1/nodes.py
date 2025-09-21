import glob
import logging
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_openai import ChatOpenAI
from tavily import TavilyClient

from nkaa.research_agent_v1.utils import (
    load_prompt,  # utils.py に移動した load_prompt をインポート
)


# --- Base Node ---
class Node(ABC):  # ABCを継承して抽象クラスであることを明示
    """グラフ内の各処理単位を表す抽象基底クラス。"""

    def __init__(self, name: str, state: str = "initialized"):
        self.name = name
        # state はデバッグやロギング目的で使用。グラフの状態管理は AgentState で行う。
        self.state = state
        logging.debug(f"Node {self.name} initialized.")

    def set_state(self, state: str):
        """ノードの内部状態を更新する（主にデバッグ用）。"""
        self.state = state
        logging.debug(f"Node {self.name} state updated to {state}")

    @abstractmethod
    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """ノードの主処理を実行する抽象メソッド。
        Args:
            input_data: ノードの実行に必要なデータを含む辞書。
        Returns:
            グラフの状態 (AgentState) を更新するためのキーと値を含む辞書。
            エラーが発生した場合は {'error': 'エラーメッセージ'} を返すことを想定。
        """
        raise NotImplementedError("Subclasses must implement run method")


# --- Search Method Interface ---
class SearchMethod(ABC):
    """情報源からデータを検索するための抽象インターフェース。"""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def search(self, query: str, options: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """指定されたクエリで検索を実行する抽象メソッド。
        Args:
            query: 検索クエリ文字列。
            options: 検索オプションを含む辞書 (例: max_results)。
        Returns:
            検索結果を含む辞書。{'results': [...], 'source': self.name} または
            {'error': 'エラーメッセージ', 'source': self.name} の形式を想定。
        """
        raise NotImplementedError("Subclasses must implement search method")


# --- Concrete Search Methods ---
class KeywordWebSearch(SearchMethod):
    """Tavily API を利用した Web 検索メソッド。"""

    def __init__(self, name: str = "keyword_web_search"):
        super().__init__(name)

    def search(self, query: str, options: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Tavily API を使用して Web 検索を実行する。"""
        logging.info(f"Executing KeywordWebSearch for query: {query}")
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            logging.error("TAVILY_API_KEY environment variable not set.")
            return {"error": "Tavily API key not configured.", "source": self.name}

        try:
            client = TavilyClient(api_key=api_key)
            # オプションがあれば適用、なければデフォルト値を使用
            opts = options or {}
            max_results = opts.get("max_results", 5)
            # Tavily の search_depth は 'basic' または 'advanced'。'advanced' の方が詳細な結果を返す傾向。
            # 他の検索エンジン (例: Google Search API) を使う場合は、パラメータ名を合わせる必要がある。
            search_depth = opts.get("search_depth", "advanced")
            # include_answer=True は質問応答形式のクエリに有効だが、汎用的な検索では False が無難。
            include_answer = opts.get("include_answer", False)

            response = client.search(
                query=query,
                search_depth=search_depth,
                max_results=max_results,
                include_answer=include_answer,
                # 必要に応じて他のパラメータ (include_raw_content, include_images) もオプション化可能
            )

            # Tavily のレスポンス形式 {'results': [{'title': ..., 'url': ..., 'content': ...}, ...]} を想定
            # 結果を整形して返す (ここでは title: content (url) の形式)
            search_results = [
                f"{res.get('title', 'N/A')}: {res.get('content', 'N/A')} ({res.get('url', 'N/A')})"
                for res in response.get("results", [])
            ]

            logging.debug(f"Tavily search completed. Found {len(search_results)} results.")
            return {"results": search_results, "source": self.name}

        except Exception as e:
            logging.error(f"Error during Tavily search: {e}", exc_info=True)
            return {"error": f"Tavily search failed: {e}", "source": self.name}


class LocalFileSearch(SearchMethod):
    """指定されたディレクトリ以下で、ファイル名またはファイル内容にクエリが部分一致するファイルを検索する。"""

    def __init__(
        self,
        name: str = "local_file_search",
        directory: str = ".",
        search_contents: bool = False,
    ):
        super().__init__(name)
        # 検索対象のルートディレクトリ
        self.directory = directory
        # ファイル内容も検索するかどうかのフラグ
        self.search_contents = search_contents

    def search(self, query: str, options: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """指定されたディレクトリ内で、ファイル名またはファイル内容にクエリが部分一致するファイルを検索する。"""
        logging.info(f"Executing LocalFileSearch in '{self.directory}' for query: '{query}'")
        matched_files = []
        try:
            if not os.path.isdir(self.directory):
                logging.error(f"Directory not found: {self.directory}")
                return {
                    "error": f"Directory not found: {self.directory}",
                    "source": self.name,
                }

            # glob を使用してディレクトリ内を再帰的に検索するパターンを作成
            # '**/*' はカレントディレクトリ以下の全てのファイルとディレクトリにマッチする
            search_pattern = os.path.join(self.directory, "**", "*")

            # recursive=True で再帰的に検索
            all_paths = glob.glob(search_pattern, recursive=True)

            # 取得したパスの中からファイルのみを対象とし、ファイル名またはファイル内容がクエリに部分一致するか確認
            # re.search を使用し、re.IGNORECASE で大文字小文字を区別しない
            for file_path in all_paths:
                if os.path.isfile(file_path):
                    filename = os.path.basename(file_path)
                    if re.search(query, filename, re.IGNORECASE):
                        matched_files.append(file_path)
                    elif self.search_contents and file_path.endswith(
                        (".txt", ".md", ".py", ".js", ".html", ".css")
                    ):  # テキストファイルのみ内容を検索
                        try:
                            with open(file_path, "r", encoding="utf-8") as f:
                                file_content = f.read()
                                if re.search(query, file_content, re.IGNORECASE):
                                    matched_files.append(f"{file_path} (内容一致)")  # ファイルパスと内容一致を明示
                        except Exception as e:
                            logging.error(f"Error reading file {file_path}: {e}")  # ファイル読み込みエラーをログ出力

            logging.debug(f"Local file search completed. Found {len(matched_files)} matching files.")
            return {"results": matched_files, "source": self.name}

        except Exception as e:
            logging.error(f"Error during local file search: {e}", exc_info=True)
            return {"error": f"Local file search failed: {e}", "source": self.name}


# --- Data Gathering Agent ---
class DataGatheringAgent(Node):
    """複数の検索メソッドを利用して情報収集を行うエージェント。"""

    def __init__(
        self,
        name: str = "DataGatheringAgent",
        search_methods: List[SearchMethod] | None = None,
    ):
        super().__init__(name)
        # デフォルトで Web 検索とローカルファイル検索を使用する。
        # 外部から異なる検索メソッドのリストを注入することも可能 (依存性注入)。
        self.search_methods = search_methods or [KeywordWebSearch(), LocalFileSearch()]
        self.results: Dict[str, Any] = {}  # 検索結果を一時的に保持 (デバッグ用)

    def add_search_method(self, method: SearchMethod):
        """検索メソッドを動的に追加する。"""
        if isinstance(method, SearchMethod):
            self.search_methods.append(method)
            logging.debug(f"Search method {method.name} added to {self.name}")
        else:
            logging.error("Invalid search method type.")

    def execute_search(self, query: str, options: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """登録されている全ての検索メソッドを実行し、結果を集約する。"""
        results = {}
        self.set_state("searching")
        logging.info(f"{self.name} starting search for query: '{query}'")
        for method in self.search_methods:
            try:
                result = method.search(query, options)
                results[method.name] = result
                logging.debug(f"Search method {method.name} completed.")
            except Exception as e:
                # 個別の検索メソッドでエラーが発生しても、他のメソッドの実行は継続する
                logging.error(f"Error in search method {method.name}: {e}")
                results[method.name] = {"error": str(e), "source": method.name}
        self.results = results  # デバッグ用に保持
        self.set_state("completed_search")
        logging.info(f"{self.name} finished search.")
        return results

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """エージェントの主処理: クエリで検索を実行し、結果またはエラーを返す。"""
        # 再計画されたクエリがあればそれを優先する
        query_to_use = input_data.get("refined_query") or input_data.get("query", "")
        original_query = input_data.get("query", "")  # ログ用

        if not query_to_use:
            logging.warning(f"{self.name} received empty query (original: '{original_query}').")
            self.set_state("error_no_query")
            # エラー情報を AgentState に反映させるために返す
            return {"error": "Query is empty"}

        options = input_data.get("options", {})
        results = self.execute_search(query_to_use, options)

        # いずれかの検索メソッドでエラーが発生したかチェック
        errors = {k: v.get("error") for k, v in results.items() if isinstance(v, dict) and "error" in v}
        if errors:
            # 複数のエラーメッセージを結合して返す
            combined_error = "; ".join([f"{k}: {e}" for k, e in errors.items()])
            return {"error": f"Data gathering failed: {combined_error}"}

        # 成功した結果のみを AgentState 更新用に返す
        successful_results = {k: v for k, v in results.items() if not (isinstance(v, dict) and "error" in v)}
        # AgentState の data_gathering_results を更新する形式で返す
        return {"data_gathering_results": successful_results}


# --- Analysis Method Interface ---
class AnalysisMethod(ABC):
    """収集されたデータを分析するための抽象インターフェース。"""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """データを分析する抽象メソッド。
        Args:
            data: DataGatheringAgent からの出力結果。
        Returns:
            分析結果を含む辞書。{'summary': '...', 'source': self.name} や
            {'keywords': [...], 'source': self.name} または
            {'error': '...', 'source': self.name} の形式を想定。
        """
        raise NotImplementedError("Subclasses must implement analyze method")


# --- Pydantic Models for Structured Output ---
# LLMに関数呼び出し (Function Calling) や構造化出力 (Structured Output) をさせる際に、
# 出力形式を Pydantic モデルで定義すると、型安全性とパースの容易性が向上する。
class KeywordsOutput(BaseModel):
    """キーワード抽出の出力スキーマ定義。"""

    keywords: List[str] = Field(description="抽出されたキーワードのリスト")


class SynthesisOutput(BaseModel):
    """統合結果の出力スキーマ定義。"""

    overall_summary: str = Field(description="分析結果全体の要約")
    key_insights: List[str] = Field(description="抽出された主要な洞察や結論のリスト")
    confidence_score: float = Field(description="結果に対する信頼度スコア (0.0-1.0)", ge=0.0, le=1.0)


# --- Concrete Analysis Methods ---
class TextSummarization(AnalysisMethod):
    """収集されたテキストデータを要約する分析メソッド。"""

    def __init__(self, name: str = "text_summarization"):
        super().__init__(name)

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """LangChain と OpenAI を使用してテキストデータを要約する。"""
        logging.info("Executing TextSummarization.")
        # data は {'search_method_name': {'results': [...], 'source': ...}, ...} の形式を想定
        # 全ての検索結果 (results) を結合して一つのテキストにする
        text_to_summarize = ""
        for source, result_data in data.items():
            if isinstance(result_data, dict) and "results" in result_data:
                results_list = result_data["results"]
                if isinstance(results_list, list):
                    text_to_summarize += f"\n--- Source: {source} ---\n"
                    # 各結果が文字列であることを想定。異なる型の場合は適切に変換が必要。
                    text_to_summarize += "\n".join(map(str, results_list))
                else:
                    logging.warning(f"Unexpected format for results in {source}: {results_list}")
            else:
                logging.warning(f"Skipping unexpected data format for source: {source}")

        if not text_to_summarize.strip():
            logging.warning("No text content found to summarize.")
            return {
                "summary": "No content available for summarization.",
                "source": self.name,
            }

        try:
            # LLM (OpenAI GPT-4o) を初期化。temperature=0 で決定的な出力を目指す。
            # 他のモデル (例: Claude, Gemini) を使う場合は、対応する LangChain インテグレーションを使用する。
            llm = ChatOpenAI(model="gpt-4o", temperature=0)

            # Jinja2 テンプレートからプロンプトを生成
            prompt_template_str = load_prompt("summarize.j2", text="{text}")
            prompt = ChatPromptTemplate.from_template(prompt_template_str)

            # 出力は単純な文字列なので StrOutputParser を使用
            parser = StrOutputParser()

            # LangChain Expression Language (LCEL) を使用してチェーンを構築・実行
            chain = prompt | llm | parser
            summary = chain.invoke({"text": text_to_summarize})

            logging.debug("Text summarization completed successfully.")
            return {"summary": summary, "source": self.name}

        except Exception as e:
            logging.error(f"Error during text summarization: {e}", exc_info=True)
            return {"error": f"Summarization failed: {e}", "source": self.name}


class KeywordExtraction(AnalysisMethod):
    """収集されたテキストデータからキーワードを抽出する分析メソッド。"""

    def __init__(self, name: str = "keyword_extraction"):
        super().__init__(name)

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """LangChain と OpenAI を使用してテキストデータからキーワードを抽出する。"""
        logging.info("Executing KeywordExtraction.")
        # 全ての検索結果を結合
        text_to_analyze = ""
        for source, result_data in data.items():
            if isinstance(result_data, dict) and "results" in result_data:
                results_list = result_data["results"]
                if isinstance(results_list, list):
                    text_to_analyze += f"\n--- Source: {source} ---\n"
                    text_to_analyze += "\n".join(map(str, results_list))
                else:
                    logging.warning(f"Unexpected format for results in {source}: {results_list}")
            else:
                logging.warning(f"Skipping unexpected data format for source: {source}")

        if not text_to_analyze.strip():
            logging.warning("No text content found for keyword extraction.")
            return {"keywords": [], "source": self.name}

        try:
            llm = ChatOpenAI(model="gpt-4o", temperature=0)

            # Pydantic モデル (KeywordsOutput) を使用して JSON 出力をパースする
            parser = JsonOutputParser(pydantic_object=KeywordsOutput)

            # プロンプトテンプレートをロード。format_instructions を含めることで、
            # LLM に期待する JSON 形式を指示する。
            prompt_template_str = load_prompt(
                "extract_keywords.j2",
                text="{text}",
                format_instructions="{format_instructions}",
            )
            # Jinja でレンダリングされたプロンプト文字列全体をテンプレートとして使用
            # プロンプト内でシステムメッセージとユーザーメッセージを区別したい場合は、
            # ChatPromptTemplate.from_messages を使用する方が適切かもしれない。
            prompt = ChatPromptTemplate.from_template(prompt_template_str)

            # LCEL チェーン
            chain = prompt | llm | parser
            # invoke にはテンプレート内の変数と format_instructions を渡す
            extracted_data = chain.invoke(
                {
                    "text": text_to_analyze,
                    "format_instructions": parser.get_format_instructions(),
                }
            )

            logging.debug("Keyword extraction completed successfully.")
            # parser により extracted_data は {'keywords': [...]} 形式の辞書になる
            return {"keywords": extracted_data.get("keywords", []), "source": self.name}

        except Exception as e:
            logging.error(f"Error during keyword extraction: {e}", exc_info=True)
            return {"error": f"Keyword extraction failed: {e}", "source": self.name}


# --- Analysis & Synthesis Agent ---
class AnalysisSynthesisAgent(Node):
    """複数の分析メソッドを実行し、その結果を統合して洞察を生成するエージェント。"""

    def __init__(
        self,
        name: str = "AnalysisSynthesisAgent",
        analysis_methods: List[AnalysisMethod] | None = None,
    ):
        super().__init__(name)
        # デフォルトで要約とキーワード抽出を使用
        self.analysis_methods = analysis_methods or [
            TextSummarization(),
            KeywordExtraction(),
        ]
        self.analysis_results: Dict[str, Any] = {}  # デバッグ用
        self.synthesis_result: Dict[str, Any] = {}  # デバッグ用

    def add_analysis_method(self, method: AnalysisMethod):
        """分析メソッドを動的に追加する。"""
        if isinstance(method, AnalysisMethod):
            self.analysis_methods.append(method)
            logging.debug(f"Analysis method {method.name} added to {self.name}")
        else:
            logging.error("Invalid analysis method type.")

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """登録されている全ての分析メソッドを実行し、結果を集約する。"""
        results = {}
        self.set_state("analyzing")
        logging.info(f"{self.name} starting analysis.")
        for method in self.analysis_methods:
            try:
                result = method.analyze(data)
                results[method.name] = result
                logging.debug(f"Analysis method {method.name} completed.")
            except Exception as e:
                # 個別の分析メソッドでエラーが発生しても継続
                logging.error(f"Error in analysis method {method.name}: {e}")
                results[method.name] = {"error": str(e), "source": method.name}
        self.analysis_results = results  # デバッグ用
        self.set_state("completed_analysis")
        logging.info(f"{self.name} finished analysis.")
        return results

    def synthesize(self, analysis_results: Dict[str, Any]) -> Dict[str, Any]:
        """LLM を使用して分析結果 (要約とキーワード) を統合し、構造化された洞察を生成する。"""
        self.set_state("synthesizing")
        logging.info(f"{self.name} starting synthesis.")

        # 分析結果から要約とキーワードを取得 (エラーがあればそれも取得)
        summary_data = analysis_results.get("text_summarization", {})
        keyword_data = analysis_results.get("keyword_extraction", {})

        # 分析ステップでエラーが発生していた場合は統合をスキップ
        if summary_data.get("error") or keyword_data.get("error"):
            error_msg = f"Synthesis skipped due to errors in analysis: Summarization Error: {summary_data.get('error', 'None')}, Keyword Error: {keyword_data.get('error', 'None')}"
            logging.error(error_msg)
            # 統合ステップでのエラーとして返す
            return {"error": error_msg}

        summary = summary_data.get("summary", "N/A")
        keywords = keyword_data.get("keywords", [])

        # 要約もキーワードもない場合は統合できない
        if summary == "N/A" and not keywords:
            logging.warning("No summary or keywords available for synthesis.")
            # エラーではないが、空の結果を返す
            return {
                "overall_summary": "No summary available.",
                "key_insights": [],
                "confidence_score": 0.0,
            }

        try:
            # 統合処理用のLLM。要約やキーワード抽出とは異なる設定 (temperature) を使うことも考えられる。
            llm = ChatOpenAI(model="gpt-4o", temperature=0.5)

            # Pydantic モデル (SynthesisOutput) を使用して JSON 出力をパース
            parser = JsonOutputParser(pydantic_object=SynthesisOutput)

            # 統合用プロンプトをロード
            prompt_template_str = load_prompt(
                "synthesize.j2",
                summary="{summary}",
                keywords="{keywords}",
                format_instructions="{format_instructions}",
            )
            prompt = ChatPromptTemplate.from_template(prompt_template_str)

            # LCEL チェーン
            chain = prompt | llm | parser
            synthesis_result = chain.invoke(
                {
                    "summary": summary,
                    "keywords": ", ".join(keywords),  # キーワードリストを文字列に変換
                    "format_instructions": parser.get_format_instructions(),
                }
            )

            # synthesis_result は SynthesisOutput スキーマに準拠した辞書
            self.synthesis_result = synthesis_result  # デバッグ用
            self.set_state("completed_synthesis")
            logging.info(f"{self.name} finished synthesis.")
            return synthesis_result  # パースされた辞書をそのまま返す

        except Exception as e:
            logging.error(f"Error during synthesis: {e}", exc_info=True)
            return {"error": f"Synthesis failed: {e}"}

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """エージェントの主処理: データ分析と結果統合を実行する。"""
        # graph.py の analyze_synthesize_node から呼び出されることを想定
        # input_data は {'results': data_gathering_results} の形式
        search_results = input_data.get("results", {})
        if not search_results:
            logging.warning(f"{self.name} received empty search results.")
            self.set_state("error_no_data")
            return {"error": "No search results to analyze"}

        analysis_results = self.analyze(search_results)
        synthesis_result = self.synthesize(analysis_results)  # synthesize はエラー情報を含む可能性あり

        # AgentState の analysis_results と synthesis_results を更新する形式で返す
        return {
            "analysis_results": analysis_results,
            "synthesis_results": synthesis_result,
        }


# --- Replan Agent ---
class ReplanAgent(Node):
    """最終チェックで「不適合」と判断された場合に、検索クエリを改善するエージェント。"""

    def __init__(self, name: str = "ReplanAgent"):
        super().__init__(name)

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """LLM を使用して、元のクエリ、統合結果、不適合理由に基づいて新しいクエリを生成する。"""
        self.set_state("replanning")
        logging.info(f"{self.name} starting query replanning.")

        original_query = input_data.get("query")
        synthesis_results = input_data.get("synthesis_results")
        final_check_results = input_data.get("final_check_results")
        current_retry_count = input_data.get("retry_count", 0)

        # 再計画に必要な情報が不足している場合はエラー
        if not original_query or not synthesis_results or not final_check_results:
            error_msg = "Replanning skipped: Missing original query, synthesis results, or final check results."
            logging.warning(error_msg)
            # retry_count はインクリメントせず、エラーを返す
            return {"error": error_msg, "retry_count": current_retry_count}

        # 不適合と判断された理由を取得
        reason = final_check_results.get("reason", "不明な理由")
        summary = synthesis_results.get("overall_summary", "N/A")
        insights = "; ".join(synthesis_results.get("key_insights", []))

        try:
            # クエリ生成用のLLM。創造性を促すために temperature を少し上げる。
            llm = ChatOpenAI(model="gpt-4o", temperature=0.7)

            # 再計画用プロンプトをロード
            prompt_template_str = load_prompt(
                "replan_query.j2",
                original_query=original_query,
                summary=summary,
                insights=insights,
                reason=reason,
            )
            prompt = ChatPromptTemplate.from_template(prompt_template_str)

            # 出力は新しいクエリ文字列
            parser = StrOutputParser()

            # LCEL チェーン
            chain = prompt | llm | parser
            # プロンプトに変数が埋め込まれているため、invoke に渡す辞書は空
            refined_query = chain.invoke({})

            # LLMが空のクエリを生成した場合のフォールバック
            if not refined_query or not refined_query.strip():
                logging.warning("LLM generated an empty refined query. Using original query for retry.")
                refined_query = original_query  # 元のクエリで再試行

            self.set_state("completed_replanning")
            logging.info(f"{self.name} finished replanning. Refined query: '{refined_query}'")
            # AgentState の refined_query と retry_count を更新する形式で返す
            return {
                "refined_query": refined_query.strip(),
                "retry_count": current_retry_count + 1,  # リトライカウントを増やす
                "error": None,  # 再計画成功時はエラーをクリア
            }

        except Exception as e:
            logging.error(f"Error during query replanning: {e}", exc_info=True)
            # エラー発生時も retry_count はインクリメントされている可能性があるため、そのまま返す
            return {
                "error": f"Replanning failed: {e}",
                "retry_count": current_retry_count + 1,
            }


# --- Pydantic Models for Structured Output ---
# (KeywordsOutput, SynthesisOutput は既に定義済み)


class FinalCheckOutput(BaseModel):
    """最終チェック結果の出力スキーマ定義。"""

    evaluation: str = Field(description="元の質問に対する結果の適合性評価（例: 適合, 不適合, 要確認）")
    reason: str = Field(description="評価の理由")


# --- Final Check Agent ---
class FinalCheckAgent(Node):
    """生成された最終結果が、元の質問の意図に適合しているかを評価するエージェント。"""

    def __init__(self, name: str = "FinalCheckAgent"):
        super().__init__(name)

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """LLM を使用して、統合結果 (synthesis_results) が元のクエリに適合するかを評価する。"""
        self.set_state("checking")
        logging.info(f"{self.name} starting final check.")

        query = input_data.get("query")
        synthesis_results = input_data.get("synthesis_results")
        # organize_results_node からのエラー情報を考慮するため final_results も参照
        final_results_from_organizer = input_data.get("final_results")

        # 前段 (organize_results や synthesize) でエラーが発生しているかチェック
        if final_results_from_organizer and final_results_from_organizer.get("status") == "error":
            error_msg = (
                f"Final check skipped due to error in organize_results: {final_results_from_organizer.get('message')}"
            )
            logging.warning(error_msg)
            # エラー情報を check_error として返し、評価は「スキップ」とする
            return {
                "check_error": error_msg,
                "final_check_results": {"evaluation": "スキップ", "reason": error_msg},
            }
        elif not synthesis_results:
            error_msg = "Final check skipped: Synthesis results are missing or invalid."
            logging.warning(error_msg)
            return {
                "check_error": error_msg,
                "final_check_results": {"evaluation": "スキップ", "reason": error_msg},
            }
        elif synthesis_results.get("error"):
            error_msg = f"Final check skipped due to error in synthesis: {synthesis_results.get('error')}"
            logging.warning(error_msg)
            return {
                "check_error": error_msg,
                "final_check_results": {"evaluation": "スキップ", "reason": error_msg},
            }
        elif not query:
            error_msg = "Final check skipped: Query is missing."
            logging.warning(error_msg)
            return {
                "check_error": error_msg,
                "final_check_results": {"evaluation": "スキップ", "reason": error_msg},
            }

        # LLM に評価させるためのテキストを準備
        synthesis_text = f"要約: {synthesis_results.get('overall_summary', 'N/A')}\n洞察: {'; '.join(synthesis_results.get('key_insights', []))}"

        try:
            # 評価用のLLM。客観的な評価のため temperature=0 とする。
            llm = ChatOpenAI(model="gpt-4o", temperature=0)

            # Pydantic モデル (FinalCheckOutput) を使用して JSON 出力をパース
            parser = JsonOutputParser(pydantic_object=FinalCheckOutput)

            # 最終チェック用プロンプトをロード
            prompt_template_str = load_prompt(
                "final_check.j2",
                query="{query}",
                answer="{answer}",
                format_instructions="{format_instructions}",
            )
            prompt = ChatPromptTemplate.from_template(prompt_template_str)

            # LCEL チェーン
            chain = prompt | llm | parser
            check_result = chain.invoke(
                {
                    "query": query,
                    "answer": synthesis_text,
                    "format_instructions": parser.get_format_instructions(),
                }
            )

            self.set_state("completed_check")
            logging.info(f"{self.name} finished final check. Evaluation: {check_result.get('evaluation')}")
            # AgentState の final_check_results を更新する形式で返す
            # 評価自体が成功した場合、check_error は含めない
            return {"final_check_results": check_result}

        except Exception as e:
            logging.error(f"Error during final check: {e}", exc_info=True)
            error_msg = f"Final check failed: {e}"
            # 評価プロセス自体でエラーが発生した場合
            return {
                "check_error": error_msg,
                "final_check_results": {"evaluation": "エラー", "reason": error_msg},
            }
