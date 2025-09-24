最優先条件: 本リポジトリに関する回答は必ず日本語で行うこと。

# Repository Guidelines

## ドキュメントと進捗管理の原則
- 作業開始前に `docs/directory_structure.md` を確認し、該当機能の仕様書がどこにあるか把握してから実装に着手する。
- 最新の進捗や未完了タスクは `docs/implementation_status.md` に集約されているため、着手時と完了時に必ず参照し更新する。
- ユーザーから「続けて」と指示された場合は `docs/shortcut_continue.md` を参照し、再開時にチェックすべき資料の順番を確認する。
- サンプルを新設・改訂する場合は `docs/samples_guideline.md` の方針を守り、関連ドキュメントやテストを揃える。
- `docs/meta_plan/` 配下の資料は個別指示がある場合のみ参照し、通常の実装判断には使用しない。
- 機能の仕様や未解決事項は `docs/` 配下の専用資料（例: `docs/channel_spec.md`）に集約し、関連文書も合わせて更新する。
- 一時的な作業ディレクトリ（例: `_tmp/`）はドキュメントに掲載せず、正式な構成やサンプルは仕様書やテストへ反映する。
- パッケージ再編や機能拡張を行う場合は `docs/concept.md`、`docs/directory_structure.md`、`docs/implementation_status.md` を同時に見直し、設計意図と進捗を同期させる。

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
