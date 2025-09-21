from typing import Any, Dict, List, Optional, TypedDict

from pydantic import BaseModel, Field


class StructuredError(BaseModel):
    """構造化されたエラー情報を保持するモデル。"""

    node_name: str = Field(..., description="エラーが発生したノード名")
    error_code: str = Field(..., description="エラーの種類を示すコード (例: APIError, ValidationError)")
    message: str = Field(..., description="エラーメッセージ")
    details: Optional[Dict[str, Any]] = Field(None, description="エラーに関する追加詳細情報")


class AgentState(TypedDict):
    """エージェントのワークフロー全体で共有される状態。"""

    initial_query: str  # ユーザーからの最初のクエリ
    current_query: str  # 現在処理中のクエリ (再計画で変更される可能性あり)
    search_plan: Optional[List[str]]  # 検索キーワードや実行する検索戦略のリスト
    search_results: List[Dict[str, Any]]  # 検索結果のリスト。各要素はソース(web/local)、URL/パス、コンテンツを含む辞書
    analysis_results: Dict[str, Any]  # 分析メソッドごとの結果を格納する辞書 (例: {"summary": "...", "keywords": [...]})
    synthesis_result: Optional[str]  # 分析結果を統合した最終的なテキスト
    final_check_passed: Optional[bool]  # 最終チェックの結果 (True: 合格, False: 不合格)
    replan_needed: bool  # 再計画が必要かどうかのフラグ
    error_info: Optional[StructuredError]  # 発生したエラーの情報 (エラーがない場合は None)
    replan_attempts: int  # 再計画の試行回数カウンター (デフォルト値は削除)
    # 必要に応じて他の状態フィールドを追加
