最優先条件: 本リポジトリに関する回答は必ず日本語で行うこと。

# Repository Guidelines

## 標準ワークフロー
1. 着手前
   - 軽微な修正や限定的な確認であれば、以下の簡易ガイドで構成を把握してから開始してもよい:
     - `nkaa/`: フレームワーク本体（エージェント・チャネル抽象）
     - `docs/`: 仕様・運用ドキュメント全般
     - `docs/workflows/`: ExecPlan や追加ワークフローなど特殊手順のガイド
     - `docs/specs/`: 機能・チャネルなどの仕様ドキュメント
     - `docs/meta_plan/`: コーディング指針や共通ポリシー集
     - `samples/`: 最小サンプルコードと手順
     - `_tmp/`: 一時ファイル置き場（成果物は正式ドキュメントへ記載しない）
   - 上記で不足する場合や広い影響を持つ作業では `docs/directory_structure.md` を参照し、関連仕様書と資料の所在を特定する。
   - 追加ワークフローが必要かを確認し、該当すればワークフロー節の条件に従って `docs/workflows/` 配下のガイドを参照する。

2. 作業中
   - 仕様や未解決事項は担当ドキュメント（例: `docs/specs/channel_spec.md`、`docs/concept.md`）に随時反映し、複数ファイルに関係する場合は相互リンクを付ける。
   - サンプルの新設・改訂は `docs/samples_guideline.md` に従い、実装・ドキュメント・テストを同時更新する。
   - パッケージ再編や機能拡張に着手した場合は、並行して `docs/directory_structure.md` と `docs/concept.md` の整合性を保つ。

3. 完了後
   - `docs/implementation_status.md` の該当項目を更新し、完了／保留／フォローアップの状態と参照リンクを記録する。
   - ユーザーから「続けて」と指示された場合は `docs/shortcut_continue.md` を参照し、再開時に確認すべき資料の順番を示す。

## ワークフロー
- **ExecPlan ワークフロー**  
  - **目的**: 複雑または長時間かかるタスクを自己完結型の設計書にまとめ、誰でも再現できる手順として共有する。  
  - **トリガー**: 調査を含め数時間以上の作業、広範囲なリファクタリング、新規機能設計など大規模な変更に着手するとき。  
  - **詳細**: `docs/workflows/exec_plan_guidelines.md` を参照。このワークフローを実施時に必ず参照すること。
- **ワークフロー追加ワークフロー**  
  - **目的**: 外部資料で定義された運用ルールを、このリポジトリの標準ワークフローとして共有可能な形に整理する。  
  - **適用例**: URL などで新しいフローが指定された場合や、既存ワークフローではカバーできない開発手順を統一したい場合。  
  - **詳細**: `docs/workflows/workflow_addition_guidelines.md` を参照。このワークフローを実施時に必ず参照すること。

## プロジェクト構造とモジュール
- コアフレームワークは `nkaa/framework/` に集約され、エージェントおよびチャネル抽象を提供する。
- プリセットとアダプターは `nkaa/presets/` に配置し、新規エージェントやツールの統合を容易にする。
- レガシー試作は `nkaa/legacy/research_agent_v1/` と `nkaa/legacy/research_agent_v2/` に保管し、参照のみで改変しない。
- 設計メモやチェックリストは `docs/concept.md` と `docs/implementation_status.md` を確認する。
- ルート直下の `pyproject.toml`、`Makefile`、`config.yaml` が開発設定を管理する。

## ビルド・テスト・開発コマンド
- Codex 実行環境では `_tmp/codex_venv` を専用の仮想環境として利用する。`UV_PROJECT_ENVIRONMENT=_tmp/codex_venv uv sync --group dev` を実行し、ホスト/コンテナ間で共通のパスを使う。
- `uv` が利用できない場合は `python -m venv _tmp/codex_venv` で仮想環境を作成し、`source _tmp/codex_venv/bin/activate && pip install -e . && pip install ruff mypy pytest` を実行する。
- `make lint` は Ruff と mypy を実行し、`nkaa/` 以下を静的チェックする。
- `make format` は Ruff フォーマッタと自動修正を適用し、コードスタイルを揃える。
- `make test` または `pytest` でテストを実行する。個別モジュールを対象にする場合は `pytest path/to/module` を利用する。

## コーディング規約と命名
- インデントは4スペース、行長は120文字以下とし、`ruff format` によるダブルクオート化と import 順序に従う。
- モジュール・関数は snake_case、クラスは CapWords、設定クラスは `<Role>Config` の命名規則を用いる。
- 公開 API には型注釈を付け、`pyproject.toml` の mypy 設定に従って戻り値を明示する。
- 副作用はマネージャ層またはツール層に集約し、フレームワーク層は宣言的に保つ。

## テスト方針
- pytest を基盤とし、対象モジュールと対応するテスト（例: `agent.py` ↔ `test_agent.py`）を揃える。
- チャネルキュー、マネージャライフサイクル、アダプター経路の正常系と例外系を網羅する。
- LLM や I/O 依存はプリセット内のフェイクツールで代替し、テストを決定的にする。
- バグ修正では回帰テストを追加し、`make test` の実行結果を PR 説明に記載する。

## コミットと Pull Request
- コミットメッセージは命令形とスコープ接頭辞（例: `framework: add channel persistence`）を用い、`wip` を避ける。
- PR 前に rebase または squash で履歴を整理し、差分を明瞭にする。
- PR 説明では目的・変更点・検証内容（例: `make lint && make test`）を記し、関連 Issue やドキュメントを紐付ける。
- ユーザー影響がある変更ではログやスクリーンショットを添付する。
- ファイル編集は `cat <<EOF > file` ではなく `apply_patch` などの差分適用を使用し、既存内容を安全に保つ。

## エージェントとチャネルの実装ヒント
- 実装前に `docs/concept.md` および `docs/implementation_status.md` の未完事項を確認し、方針を固める。
- 新規エージェントは `StandardManager` と `nkaa/presets/managers/single_agent_model.py` のアダプターパターンを再利用する。
- 実運用ツールは `nkaa/presets/tools/` を拡張し、設定オプションや依存関係をドキュメントへ反映する。
