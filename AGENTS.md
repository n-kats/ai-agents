# Repository Guidelines

## プロジェクト構造 と モジュール
- コア フレームワーク は `nkaa/framework/` に 集約 され、エージェント・チャネル 抽象 を 提供 します。
- プリセット と アダプター は `nkaa/presets/` に 置き、新規 エージェント や ツール を 統合 します。
- レガシー 試作 は `nkaa/research_agent_v1/` と `nkaa/research_agent_v2/`、参照 のみ で 改変 禁止 です。
- 設計 メモ と チェックリスト は `docs/concept.md` と `docs/implementation_status.md` を 確認 します。
- ルート 直下 の `pyproject.toml`、`Makefile`、`config.yaml` が 開発 設定 を 管理 します。

## ビルド・テスト・開発 コマンド
- `uv sync --group dev` で ランタイム と 開発 依存 を まとめて 導入 します。`uv` 無し なら `pip install -e .` 後 に `ruff`、`mypy`、`pytest` を 入れます。
- `make lint` は Ruff と mypy を 通し、`nkaa/` を 静的 チェック します。
- `make format` は Ruff フォーマッタ と 自動 修正 を 実行 し コード を 整えます。
- `make test` や `pytest` で テスト を 実行。個別 対象 は `pytest path/to/module` を 使用 します。

## コーディング 規約 と 命名
- インデント は 4 スペース、行長 は 120 文字 以下、`ruff format` が ダブル クオート と import 順 を 強制 します。
- モジュール・関数 は snake_case、クラス は CapWords、設定 クラス は `<Role>Config` を 採用 します。
- 公開 API に 型 注釈 を 付け、`pyproject.toml` の mypy 設定 に 従って 明示 戻り値 を 書きます。
- 副作用 は マネージャー 層 または ツール 層 に 集約 し、フレームワーク 層 は 宣言 的 に 保ちます。

## テスト 方針
- pytest を 基本 と し、対象 モジュール 名 と 対応 テスト 名 (`agent.py` ↔ `test_agent.py`) を 揃えます。
- チャネル キュー、マネージャー ライフサイクル、アダプター 経路 の 正常 系 と 例外 系 を カバー します。
- LLM や I/O 依存 は プリセット 内 フェイク ツール で 代替 し テスト を 決定的 に します。
- バグ 修正 では 回帰 テスト を 追加 し、`make test` 成果 を PR 説明 に 記載 します。

## コミット と Pull Request
- コミット メッセージ は 命令形 と スコープ 接頭辞 (`framework: add channel persistence`) を 使い、`wip` を 避けます。
- PR 前 に rebase か squash で 履歴 を 整理 し 差分 を 明瞭 に します。
- PR 説明 には 目的、変更 点、検証 (`make lint && make test`) を 記し、関連 Issue や ドキュメント を 紐付けます。
- ユーザー 影響 が 見える 変更 では ログ や スクリーンショット を 添付 します。
- ファイル 編集 は `cat <<EOF > file` ではなく `apply_patch` 等 の 差分 適用 で 行い、既存 内容 の 破壊 を 避けます。

## エージェント と チャネル の 実装 ヒント
- 実装 前 に `docs/concept.md` と `docs/implementation_status.md` の 未完 事項 を 確認 し 方針 を 整えます。
- 新規 エージェント は `StandardManager` と `nkaa/presets/managers/single_agent_model.py` の アダプター パターン を 再利用 します。
- 実運用 ツール は `nkaa/presets/tools/` を 拡張 し、設定 オプション と 依存 を ドキュメント に 反映 します。
