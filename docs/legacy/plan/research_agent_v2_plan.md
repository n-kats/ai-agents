# research_agent_v2 設計計画

## 1. 目標とスコープ

*   **目標:** research_agent_v1 の反省点を踏まえ、より堅牢で、保守・拡張しやすく、柔軟性の高い調査エージェント v2 を開発する。
*   **スコープ:**
    *   v1 の基本機能を維持しつつ、以下の改善点を実装する。
        *   インターフェース統一 (Agent と Graph の連携簡素化)
        *   LLM クライアントの共通化 (DI パターン導入)
        *   AgentState の構造見直しとエラー情報の構造化
        *   設定ファイルによる検索/分析メソッド、パラメータの動的指定
        *   ユニットテストおよび結合テストの導入 (**テストファイルは対象コードと同階層に配置**)
        *   設計・仕様に関するドキュメントの拡充

## 2. ディレクトリ構成案

[docs/meta_plan/directory_structure.md](../../meta_plan/directory_structure.md) を参照し、v1 の構成をベースに以下のように変更・追加する。**テストファイルは各モジュール内に配置する (`test_*.py`)。**

```
.
├── docs/
│   ├── meta_plan/
│   ├── plan/
│   │   ├── research_agent_v1.md
│   │   └── research_agent_v2_plan.md
│   ├── reflection/
│   └── usage/
├── nkaa/
│   ├── __init__.py
│   ├── py.typed
│   ├── research_agent_v1/ ...
│   └── research_agent_v2/
│       ├── __init__.py
│       ├── main.py
│       ├── test_main.py            <-- Test File Example
│       ├── graph.py
│       ├── test_graph.py           <-- Test File Example
│       ├── state.py
│       ├── test_state.py           <-- Test File Example
│       ├── nodes/
│       │   ├── __init__.py
│       │   ├── base_node.py
│       │   ├── test_base_node.py     <-- Test File Example
│       │   ├── data_gathering.py
│       │   ├── test_data_gathering.py <-- Test File Example
│       │   ├── analysis_synthesis.py
│       │   ├── test_analysis_synthesis.py <-- Test File Example
│       │   ├── final_check.py
│       │   ├── test_final_check.py   <-- Test File Example
│       │   └── replan.py
│       │   └── test_replan.py        <-- Test File Example
│       ├── methods/
│       │   ├── __init__.py
│       │   ├── base_method.py
│       │   ├── test_base_method.py   <-- Test File Example
│       │   ├── search/
│       │   │   ├── __init__.py
│       │   │   ├── web_search.py
│       │   │   ├── test_web_search.py <-- Test File Example
│       │   │   └── local_search.py
│       │   │   └── test_local_search.py <-- Test File Example
│       │   └── analysis/
│       │       ├── __init__.py
│       │       ├── summarize.py
│       │       ├── test_summarize.py   <-- Test File Example
│       │       └── keyword_extract.py
│       │       └── test_keyword_extract.py <-- Test File Example
│       ├── prompts/
│       │   ├── __init__.py
│       │   └── ...
│       ├── config/
│       │   ├── __init__.py
│       │   ├── settings.py
│       │   ├── test_settings.py      <-- Test File Example
│       │   └── default_config.yaml
│       ├── llm_clients/
│       │   ├── __init__.py
│       │   ├── client_provider.py
│       │   └── test_client_provider.py <-- Test File Example
│       └── utils/
│           ├── __init__.py
│           ├── ...
│           └── test_utils.py         <-- Test File Example
├── .env
├── pyproject.toml
├── Makefile
└── ...
```

## 3. 主要コンポーネント設計

### 3.1. AgentState (`state.py`)

*   v1 の反省を踏まえ、キーの整理と構造化を行う。
*   エラー情報を格納する専用のフィールドを設け、構造化されたエラーオブジェクト (発生ノード、エラーコード、メッセージ等) を保持する。

```python
# state.py (イメージ)
from typing import List, Dict, Any, Optional, TypedDict
from pydantic import BaseModel, Field

class StructuredError(BaseModel):
    node_name: str
    error_code: str # 例: "APIError", "ValidationError", "Timeout"
    message: str
    details: Optional[Dict[str, Any]] = None

class AgentState(TypedDict):
    initial_query: str
    current_query: str
    search_plan: Optional[List[str]] # 検索キーワードや戦略
    search_results: List[Dict[str, Any]] # { "source": "web", "url": "...", "content": "..." } or { "source": "local", "path": "...", "content": "..." }
    analysis_results: Dict[str, Any] # 分析メソッドごとの結果 (例: {"summary": "...", "keywords": [...]})
    synthesis_result: Optional[str] # 統合された結果
    final_check_passed: Optional[bool]
    replan_needed: bool
    error_info: Optional[StructuredError] # 構造化されたエラー情報
    # その他、必要に応じて追加
```

### 3.2. ノード (Agent) (`nodes/`)

*   `nodes/base_node.py` に基底クラス `BaseNode` を定義。
    *   `AgentState` を直接受け取り、更新して返すインターフェースを持つ。
    *   LLM クライアントや設定オブジェクトをコンストラクタで受け取る (DI)。
*   各 Agent (例: `DataGatheringNode`) は `BaseNode` を継承。
*   `graph.py` では、これらの Node クラスのメソッドを直接ノードとして登録し、ラッパー処理を不要にする。

### 3.3. メソッド (`methods/`)

*   `methods/base_method.py` に検索 (`BaseSearchMethod`) および分析 (`BaseAnalysisMethod`) の基底クラス (または Protocol) を定義。
*   各具体的なメソッド (例: `WebSearchMethod`, `SummarizeMethod`) はこれを実装。
*   Agent は、設定に基づいてこれらのメソッドのインスタンスを DI コンテナ等から取得して利用する。

### 3.4. LLM クライアント (`llm_clients/`)

*   `llm_clients/client_provider.py` で、設定に基づいて `ChatOpenAI` 等のクライアントインスタンスを生成・管理するファクトリや DI コンテナを実装。
*   各 Agent は、コンストラクタで必要なクライアントインスタンスを受け取る。

### 3.5. 設定管理 (`config/`)

*   `config/settings.py` で Pydantic モデルを定義し、設定ファイル (`.yaml` や `.toml`) や環境変数から設定値を読み込む。
*   設定項目例:
    *   使用する LLM モデル名、API キー、temperature 等
    *   使用する検索メソッドとそのパラメータ (例: Web 検索の API キー、ローカル検索の対象ディレクトリ)
    *   使用する分析メソッドとそのパラメータ
    *   再試行回数、タイムアウト値など

## 4. テスト戦略

*   **ユニットテスト:** 各 Agent ノード、検索/分析メソッド、ユーティリティ関数などを個別にテスト。テストコード (`test_*.py`) は、**テスト対象の Python ファイルと同じディレクトリに配置**する。モックを活用して依存関係を分離。
*   **結合テスト:** LangGraph で構築したグラフ全体の流れをテスト (`test_graph.py` や `test_main.py` などで実施)。特定の入力に対して期待される状態遷移や最終出力が得られるかを確認。

## 5. ドキュメント

*   [docs/meta_plan/docs_guidelines.md](../../meta_plan/docs_guidelines.md) に従い、以下のドキュメントを作成・更新する。
    *   `README.md`: プロジェクト概要、セットアップ、実行方法。
    *   `docs/usage/`: 使い方、設定ファイルの詳細。
    *   [docs/plan/research_agent_v2_plan.md](../plan/research_agent_v2_plan.md): この設計ドキュメント。
    *   `docs/internal/`: (必要であれば) 内部実装の詳細、クラス図、シーケンス図など。
*   コードコメントも [docs/meta_plan/comment_guidelines.md](../../meta_plan/comment_guidelines.md) に従って記述する。
