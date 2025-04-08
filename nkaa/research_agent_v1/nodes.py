import glob  # 追加
import logging
import os
import re  # 追加
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List  # 追加

from jinja2 import Environment, FileSystemLoader, select_autoescape  # 追加
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser  # 追加
from langchain_core.prompts import ChatPromptTemplate  # 追加
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_openai import ChatOpenAI
from tavily import TavilyClient

logging.basicConfig(level=logging.DEBUG)

# --- Jinja2 Environment Setup ---
# プロンプトファイルがあるディレクトリを指定
PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")
jinja_env = Environment(
    loader=FileSystemLoader(PROMPT_DIR), autoescape=select_autoescape()
)


def load_prompt(template_name: str, **kwargs) -> str:
    """Jinja2テンプレートを読み込んでレンダリングするヘルパー関数"""
    template = jinja_env.get_template(template_name)
    return template.render(**kwargs)


# --- Base Node ---
class Node:
    """基本的なノードクラス。状態を持つ。"""

    def __init__(self, name, state="initialized"):
        self.name = name
        self.state = state
        logging.debug(f"Node {self.name} initialized.")

    def set_state(self, state):
        """ノードの状態を更新する。"""
        self.state = state
        logging.debug(f"Node {self.name} state updated to {state}")

    @abstractmethod
    def run(self, input_data):
        """エージェントのメイン実行関数（サブクラスで実装）"""
        raise NotImplementedError("Subclasses must implement run method")


# --- Search Method Interface ---
class SearchMethod(ABC):
    """検索メソッドのインターフェース。"""

    def __init__(self, name):
        self.name = name

    @abstractmethod
    def search(self, query, options=None):
        """検索を実行する（サブクラスで実装）"""
        raise NotImplementedError("Subclasses must implement search method")


# --- Concrete Search Methods (Placeholders) ---
class KeywordWebSearch(SearchMethod):
    """キーワードベースのWeb検索（プレースホルダー）。"""

    def __init__(self, name="keyword_web_search"):
        super().__init__(name)

    def search(self, query, options=None):
        """Tavily API を使用して Web 検索を実行する。"""
        logging.info(f"Executing KeywordWebSearch for query: {query}")
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            logging.error("TAVILY_API_KEY environment variable not set.")
            return {"error": "Tavily API key not configured.", "source": "web"}

        try:
            client = TavilyClient(api_key=api_key)
            # options から検索パラメータを取得 (例: max_results)
            max_results = options.get("max_results", 5) if options else 5
            # Tavily API 呼び出し (search_depth は Tavily のパラメータに合わせて調整が必要な場合がある)
            # include_answer=True にすると、質問に対する直接的な回答も試みる
            response = client.search(
                query=query,
                search_depth="advanced",  # または "basic"
                max_results=max_results,
                include_answer=False,  # 回答を含めるか
                # include_raw_content=False, # 元のWebページ内容を含めるか
                # include_images=False, # 画像を含めるか
            )

            # 結果を整形
            # response['results'] は辞書 ({'title': ..., 'url': ..., 'content': ...}) のリスト
            search_results = [
                f"{res.get('title', 'N/A')}: {res.get('content', 'N/A')} ({res.get('url', 'N/A')})"
                for res in response.get("results", [])
            ]

            logging.debug(
                f"Tavily search completed. Found {len(search_results)} results."
            )
            return {"results": search_results, "source": "web"}

        except Exception as e:
            logging.error(f"Error during Tavily search: {e}", exc_info=True)
            return {"error": f"Tavily search failed: {e}", "source": "web"}


class LocalFileSearch(SearchMethod):
    """ローカルファイル検索（プレースホルダー）。"""

    def __init__(self, name="local_file_search", directory="."):
        super().__init__(name)
        self.directory = directory

    def search(self, query, options=None):
        """指定されたディレクトリ内で、ファイル名がクエリに一致するファイルを検索する。"""
        logging.info(
            f"Executing LocalFileSearch in '{self.directory}' for query: '{query}'"
        )
        matched_files = []
        try:
            # ディレクトリが存在するか確認
            if not os.path.isdir(self.directory):
                logging.error(f"Directory not found: {self.directory}")
                return {
                    "error": f"Directory not found: {self.directory}",
                    "source": "local",
                }

            # 再帰的にファイルを検索するためのパターン
            # os.path.join でOS互換のパスを作成
            search_pattern = os.path.join(self.directory, "**", "*")

            # glob でファイルとディレクトリを再帰的に取得
            all_paths = glob.glob(search_pattern, recursive=True)

            # ファイルのみを対象とし、クエリにファイル名が一致するか確認 (大文字小文字無視)
            for file_path in all_paths:
                if os.path.isfile(file_path):
                    filename = os.path.basename(file_path)
                    # re.search で部分一致、IGNORECASEで大文字小文字無視
                    if re.search(query, filename, re.IGNORECASE):
                        matched_files.append(file_path)

            logging.debug(
                f"Local file search completed. Found {len(matched_files)} matching files."
            )
            return {"results": matched_files, "source": "local"}

        except Exception as e:
            logging.error(f"Error during local file search: {e}", exc_info=True)
            return {"error": f"Local file search failed: {e}", "source": "local"}


# --- Data Gathering Agent ---
class DataGatheringAgent(Node):
    """情報収集を行うエージェント。"""

    def __init__(self, name="DataGatheringAgent", search_methods=None):
        super().__init__(name)
        # デフォルトの検索メソッドを設定
        # デフォルトの検索メソッドを設定
        self.search_methods = search_methods or [KeywordWebSearch(), LocalFileSearch()]
        self.results = {}

    def add_search_method(self, method: SearchMethod):
        """検索メソッドを追加する。"""
        if isinstance(method, SearchMethod):
            self.search_methods.append(method)
            logging.debug(f"Search method {method.name} added to {self.name}")
        else:
            logging.error("Invalid search method type.")

    def execute_search(self, query, options=None):
        """指定されたクエリで検索を実行する。"""
        results = {}
        self.set_state("searching")
        logging.info(f"{self.name} starting search for query: '{query}'")
        for method in self.search_methods:
            try:
                result = method.search(query, options)
                results[method.name] = result
                logging.debug(f"Search method {method.name} completed.")
            except Exception as e:
                logging.error(f"Error in search method {method.name}: {e}")
                results[method.name] = {"error": str(e), "source": method.name}
        self.results = results
        self.set_state("completed_search")
        logging.info(f"{self.name} finished search.")
        return results

    def run(self, input_data: Dict[str, Any]):
        """エージェントのメイン実行関数。refined_queryがあればそちらを優先する。"""
        # refined_query があればそちらを優先、なければ元の query を使用
        query_to_use = input_data.get("refined_query") or input_data.get("query", "")
        original_query = input_data.get("query", "")  # ログ用に元のクエリも保持

        if not query_to_use:
            logging.warning(
                f"{self.name} received empty query (original: '{original_query}')."
            )
            self.set_state("error_no_query")
            return {"results": {}, "state": self.state, "error": "Query is empty"}

        options = input_data.get("options", {})
        # query_to_use を使って検索を実行
        results = self.execute_search(query_to_use, options)
        # グラフ (AgentState) の更新に必要な部分のみを返す
        # エラーチェックのために results を直接評価するのではなく、
        # results 内の各メソッドの結果を確認する方が安全
        has_error = any(isinstance(v, dict) and "error" in v for v in results.values())

        if has_error:
            combined_error = "; ".join(
                [
                    f"{k}: {v.get('error', 'Unknown error')}"
                    for k, v in results.items()
                    if isinstance(v, dict) and "error" in v
                ]
            )
            if combined_error:
                return {"error": f"Data gathering failed: {combined_error}"}

        # 成功時は結果のみ返す (エラー情報は含まない)
        successful_results = {
            k: v
            for k, v in results.items()
            if not (isinstance(v, dict) and "error" in v)
        }
        return {"results": successful_results}


# --- Analysis Method Interface ---
class AnalysisMethod(ABC):
    """分析メソッドのインターフェース。"""

    def __init__(self, name):
        self.name = name

    @abstractmethod
    def analyze(self, data):
        """データを分析する（サブクラスで実装）"""
        raise NotImplementedError("Subclasses must implement analyze method")


# --- Pydantic Models for Structured Output ---
class KeywordsOutput(BaseModel):
    """キーワード抽出の出力スキーマ"""

    keywords: List[str] = Field(description="抽出されたキーワードのリスト")


class SynthesisOutput(BaseModel):
    """統合結果の出力スキーマ"""

    overall_summary: str = Field(description="分析結果全体の要約")
    key_insights: List[str] = Field(description="抽出された主要な洞察や結論のリスト")
    confidence_score: float = Field(
        description="結果に対する信頼度スコア (0.0-1.0)", ge=0.0, le=1.0
    )


# --- Concrete Analysis Methods ---
class TextSummarization(AnalysisMethod):
    """テキスト要約"""

    def __init__(self, name="text_summarization"):
        super().__init__(name)

    def analyze(self, data: Dict[str, Any]):
        """LangChain と OpenAI を使用してテキストデータを要約する。"""
        logging.info("Executing TextSummarization.")
        # data は {'search_method_name': {'results': [...], 'source': ...}, ...} の形式を想定
        # 全ての検索結果を結合して要約対象のテキストを作成
        text_to_summarize = ""
        for source, result_data in data.items():
            if isinstance(result_data, dict) and "results" in result_data:
                # 結果がリストであることを確認し、文字列に結合
                results_list = result_data["results"]
                if isinstance(results_list, list):
                    text_to_summarize += f"\n--- Source: {source} ---\n"
                    text_to_summarize += "\n".join(
                        map(str, results_list)
                    )  # 各結果を文字列に変換
                else:
                    logging.warning(
                        f"Unexpected format for results in {source}: {results_list}"
                    )
            else:
                logging.warning(f"Skipping unexpected data format for source: {source}")

        if not text_to_summarize.strip():
            logging.warning("No text content found to summarize.")
            return {
                "summary": "No content available for summarization.",
                "source": "summarization",
            }

        try:
            # OpenAI モデルの初期化 (環境変数 OPENAI_API_KEY が必要)
            # model_name は適宜変更可能 (例: "gpt-4o", "gpt-3.5-turbo")
            llm = ChatOpenAI(model_name="gpt-4o", temperature=0)

            # プロンプトテンプレートをファイルから読み込む
            prompt_template_str = load_prompt("summarize.j2", text="{text}")
            prompt = ChatPromptTemplate.from_template(prompt_template_str)

            # 出力パーサー (文字列として出力)
            parser = StrOutputParser()

            # LCEL チェーンの構築と実行
            chain = prompt | llm | parser
            summary = chain.invoke({"text": text_to_summarize})

            logging.debug("Text summarization completed successfully.")
            return {"summary": summary, "source": "summarization"}

        except Exception as e:
            logging.error(f"Error during text summarization: {e}", exc_info=True)
            return {"error": f"Summarization failed: {e}", "source": "summarization"}


class KeywordExtraction(AnalysisMethod):
    """キーワード抽出"""

    def __init__(self, name="keyword_extraction"):
        super().__init__(name)

    def analyze(self, data: Dict[str, Any]):
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
                    logging.warning(
                        f"Unexpected format for results in {source}: {results_list}"
                    )
            else:
                logging.warning(f"Skipping unexpected data format for source: {source}")

        if not text_to_analyze.strip():
            logging.warning("No text content found for keyword extraction.")
            return {"keywords": [], "source": "extraction"}

        try:
            # OpenAI モデルの初期化
            llm = ChatOpenAI(model_name="gpt-4o", temperature=0)

            # 出力スキーマに基づいたパーサー
            parser = JsonOutputParser(pydantic_object=KeywordsOutput)

            # プロンプトテンプレートをファイルから読み込む
            # Jinja2テンプレート内でシステムプロンプトとヒューマンプロンプトを分離
            prompt_template_str = load_prompt(
                "extract_keywords.j2",
                text="{text}",
                format_instructions="{format_instructions}",
            )
            # LangChainはシステム/ヒューマンの分離を直接サポートしないため、
            # レンダリングされた文字列全体を単一のテンプレートとして扱うか、
            # または手動でメッセージリストを作成する必要がある。
            # ここでは、レンダリングされた文字列を from_template で扱う。
            # (より複雑な場合は from_messages を使う方が良い場合もある)
            prompt = ChatPromptTemplate.from_template(prompt_template_str)

            # LCEL チェーン
            chain = prompt | llm | parser
            extracted_data = chain.invoke(
                {
                    "text": text_to_analyze,
                    "format_instructions": parser.get_format_instructions(),
                }
            )

            logging.debug("Keyword extraction completed successfully.")
            # extracted_data は {'keywords': [...]} の形式のはず
            return {
                "keywords": extracted_data.get("keywords", []),
                "source": "extraction",
            }

        except Exception as e:
            logging.error(f"Error during keyword extraction: {e}", exc_info=True)
            return {"error": f"Keyword extraction failed: {e}", "source": "extraction"}


# --- Analysis & Synthesis Agent ---
class AnalysisSynthesisAgent(Node):
    """分析と統合を行うエージェント。"""

    def __init__(self, name="AnalysisSynthesisAgent", analysis_methods=None):
        super().__init__(name)
        # デフォルトの分析メソッドを設定
        self.analysis_methods = analysis_methods or [
            TextSummarization(),
            KeywordExtraction(),
        ]
        self.analysis_results = {}
        self.synthesis_result = {}

    def add_analysis_method(self, method: AnalysisMethod):
        """分析メソッドを追加する。"""
        if isinstance(method, AnalysisMethod):
            self.analysis_methods.append(method)
            logging.debug(f"Analysis method {method.name} added to {self.name}")
        else:
            logging.error("Invalid analysis method type.")

    def analyze(self, data):
        """データを分析する。"""
        results = {}
        self.set_state("analyzing")
        logging.info(f"{self.name} starting analysis.")
        for method in self.analysis_methods:
            try:
                result = method.analyze(data)
                results[method.name] = result
                logging.debug(f"Analysis method {method.name} completed.")
            except Exception as e:
                logging.error(f"Error in analysis method {method.name}: {e}")
                results[method.name] = {"error": str(e), "source": method.name}
        self.analysis_results = results
        self.set_state("completed_analysis")
        logging.info(f"{self.name} finished analysis.")
        return results

    def synthesize(self, analysis_results: Dict[str, Any]):
        """LLM を使用して分析結果 (要約とキーワード) を統合し、洞察を生成する。"""
        self.set_state("synthesizing")
        logging.info(f"{self.name} starting synthesis.")

        # 分析結果から要約とキーワードを取得
        summary_data = analysis_results.get("text_summarization", {})
        keyword_data = analysis_results.get("keyword_extraction", {})

        # エラーチェック
        if summary_data.get("error") or keyword_data.get("error"):
            error_msg = f"Synthesis skipped due to errors in analysis: Summarization Error: {summary_data.get('error', 'None')}, Keyword Error: {keyword_data.get('error', 'None')}"
            logging.error(error_msg)
            # エラーがある場合は、統合結果にもエラー情報を反映させるか、空の結果を返すか検討
            # ここでは空の結果とエラー情報を返す例
            return {"error": error_msg}

        summary = summary_data.get("summary", "N/A")
        keywords = keyword_data.get("keywords", [])

        if summary == "N/A" and not keywords:
            logging.warning("No summary or keywords available for synthesis.")
            # デフォルトの空の結果を返す
            return {
                "overall_summary": "No summary available.",
                "key_insights": [],
                "confidence_score": 0.0,
            }

        try:
            # OpenAI モデルの初期化
            llm = ChatOpenAI(
                model_name="gpt-4o", temperature=0.5
            )  # 少し創造性を持たせる

            # 出力スキーマに基づいたパーサー
            parser = JsonOutputParser(pydantic_object=SynthesisOutput)

            # プロンプトテンプレートをファイルから読み込む
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
                    "keywords": ", ".join(keywords),  # リストをカンマ区切りの文字列に
                    "format_instructions": parser.get_format_instructions(),
                }
            )

            # synthesis_result は SynthesisOutput モデルに準拠した辞書のはず
            self.synthesis_result = synthesis_result
            self.set_state("completed_synthesis")
            logging.info(f"{self.name} finished synthesis.")
            return synthesis_result  # パースされた辞書をそのまま返す

        except Exception as e:
            logging.error(f"Error during synthesis: {e}", exc_info=True)
            # エラー発生時はエラー情報を含む辞書を返す
            return {"error": f"Synthesis failed: {e}"}

    def run(self, input_data):
        """エージェントのメイン実行関数。"""
        search_results = input_data.get("results", {})
        if not search_results:
            logging.warning(f"{self.name} received empty search results.")
            self.set_state("error_no_data")
            return {
                "analysis": {},
                "synthesis": {},
                "state": self.state,
                "error": "No search results to analyze",
            }

        analysis_results = self.analyze(search_results)
        synthesis = self.synthesize(analysis_results)

        return {
            "analysis": analysis_results,
            "synthesis": synthesis,
            # "state": self.state, # 状態はグラフ側で管理するため不要
        }


# --- Replan Agent ---
class ReplanAgent(Node):
    """最終チェックで不適合だった場合に、クエリを再計画するエージェント。"""

    def __init__(self, name="ReplanAgent"):
        super().__init__(name)

    def run(self, input_data: Dict[str, Any]):
        """LLM を使用して、より良い検索クエリを生成する。"""
        self.set_state("replanning")
        logging.info(f"{self.name} starting query replanning.")

        original_query = input_data.get("query")
        synthesis_results = input_data.get("synthesis_results")
        final_check_results = input_data.get("final_check_results")

        # 必要な情報が揃っているか確認
        if not original_query or not synthesis_results or not final_check_results:
            error_msg = "Replanning skipped: Missing original query, synthesis results, or final check results."
            logging.warning(error_msg)
            return {"error": error_msg}  # エラーを AgentState に記録

        # 不適合の理由を取得
        reason = final_check_results.get("reason", "不明な理由")
        summary = synthesis_results.get("overall_summary", "N/A")
        insights = "; ".join(synthesis_results.get("key_insights", []))

        try:
            # OpenAI モデルの初期化
            llm = ChatOpenAI(
                model_name="gpt-4o", temperature=0.7
            )  # 少し創造性を持たせる

            # プロンプトテンプレートをファイルから読み込む
            prompt_template_str = load_prompt(
                "replan_query.j2",
                original_query=original_query,
                summary=summary,
                insights=insights,
                reason=reason,
            )
            prompt = ChatPromptTemplate.from_template(prompt_template_str)

            # 出力パーサー (文字列として出力)
            parser = StrOutputParser()

            # LCEL チェーン
            chain = prompt | llm | parser
            refined_query = chain.invoke(
                {}
            )  # invokeに渡す辞書は空でOK (テンプレート内で変数を展開済)

            # 生成されたクエリが空でないことを確認
            if not refined_query or not refined_query.strip():
                logging.warning(
                    "LLM generated an empty refined query. Using original query for retry."
                )
                refined_query = original_query  # 空の場合は元のクエリを使う

            self.set_state("completed_replanning")
            logging.info(
                f"{self.name} finished replanning. Refined query: '{refined_query}'"
            )
            # retry_count をインクリメントし、refined_query を返す
            current_retry_count = input_data.get("retry_count", 0)
            return {
                "refined_query": refined_query.strip(),
                "retry_count": current_retry_count + 1,
                "error": None,  # 再計画成功時はエラーをクリア
            }

        except Exception as e:
            logging.error(f"Error during query replanning: {e}", exc_info=True)
            # エラー発生時はエラー情報を返す
            return {"error": f"Replanning failed: {e}"}


# --- Pydantic Models for Structured Output ---
# (KeywordsOutput, SynthesisOutput は既に定義済み)


class FinalCheckOutput(BaseModel):
    """最終チェック結果の出力スキーマ"""

    evaluation: str = Field(
        description="元の質問に対する結果の適合性評価（例: 適合, 不適合, 要確認）"
    )
    reason: str = Field(description="評価の理由")


# --- Final Check Agent ---
class FinalCheckAgent(Node):
    """最終結果が元の質問に適合しているかを確認するエージェント。"""

    def __init__(self, name="FinalCheckAgent"):
        super().__init__(name)

    def run(self, input_data: Dict[str, Any]):
        """LLM を使用して、統合結果が元のクエリに適合するかを評価する。"""
        self.set_state("checking")
        logging.info(f"{self.name} starting final check.")

        query = input_data.get("query")
        synthesis_results = input_data.get("synthesis_results")
        final_results_from_organizer = input_data.get(
            "final_results"
        )  # organize_resultsからの出力を取得

        # organize_results がエラーを返した場合など、synthesis_results がない場合がある
        if not synthesis_results:
            if final_results_from_organizer and final_results_from_organizer.get(
                "error"
            ):
                error_msg = f"Final check skipped due to error in organize_results: {final_results_from_organizer.get('error')}"
            elif not query:
                error_msg = "Final check skipped: Query is missing."
            else:
                error_msg = (
                    "Final check skipped: Synthesis results are missing or invalid."
                )
            logging.warning(error_msg)
            # AgentStateにエラー情報を記録するために返す
            return {
                "check_error": error_msg,
                "final_check_results": {"evaluation": "スキップ", "reason": error_msg},
            }

        # synthesis_results 内にエラーがある場合
        if synthesis_results.get("error"):
            error_msg = f"Final check skipped due to error in synthesis: {synthesis_results.get('error')}"
            logging.warning(error_msg)
            return {
                "check_error": error_msg,
                "final_check_results": {"evaluation": "スキップ", "reason": error_msg},
            }

        # 評価対象のテキストを作成
        synthesis_text = f"要約: {synthesis_results.get('overall_summary', 'N/A')}\n洞察: {'; '.join(synthesis_results.get('key_insights', []))}"

        try:
            # OpenAI モデルの初期化
            llm = ChatOpenAI(model_name="gpt-4o", temperature=0)

            # 出力スキーマに基づいたパーサー
            parser = JsonOutputParser(pydantic_object=FinalCheckOutput)

            # プロンプトテンプレートをファイルから読み込む
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
            logging.info(
                f"{self.name} finished final check. Evaluation: {check_result.get('evaluation')}"
            )
            # AgentStateに最終チェック結果を格納するために返す
            return {
                "final_check_results": check_result
            }  # エラーがない場合は check_error は含めない

        except Exception as e:
            logging.error(f"Error during final check: {e}", exc_info=True)
            error_msg = f"Final check failed: {e}"
            # AgentStateにエラー情報を記録するために返す
            return {
                "check_error": error_msg,
                "final_check_results": {"evaluation": "エラー", "reason": error_msg},
            }
