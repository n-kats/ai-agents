# Repository Directory Structure

このドキュメントは本リポジトリの主要ディレクトリと役割をまとめています。構成を更新した場合は、本ファイルもあわせて改訂してください。

## ルート直下
- `nkaa/` : フレームワーク本体。基盤コード、プリセット、旧研究用実装を含みます。
- `docs/` : 現行アーキテクチャや運用方針をまとめたドキュメント。
- `docs/legacy/` : 過去の Research Agent 系資料や振り返りログ。参照のみ。
- `docs/meta_plan/` : 再利用可能なテンプレートや横断的な計画メモを格納（個別ガイドライン本文は `docs/guides/` へ移動）。
- `docs/workflows/` : ExecPlan や追加ワークフローなど標準手順のガイドライン。
- `docs/plans/` : 具体的な実装計画を記録するエリア（永続化プラン、検証ログなど）。
- `docs/guides/` : サンプル方針やショートカットなどの運用ガイド。
- `docs/specs/` : 機能仕様やチャネル仕様などのリファレンス。
- `docs/notes/` : 開発メモや検討ログ。
- `docs/usage/` : `make lint` などのコマンドリファレンス。
- `docker/` : Docker Compose など環境構築用ファイル（PostgreSQL チャンネル基盤を追加予定）。
- `samples/` : フレームワークを体験するための最小サンプルコードと手順。
- `Makefile`, `pyproject.toml`, `uv.lock` : ビルドと依存管理設定。
- `_cache/`, `_output/`, `_data/` : 実行時生成物やキャッシュ（必要に応じて作成）。
- `_tmp/` : 一時ファイル群。Codex 用の仮想環境 `_tmp/codex_venv` もここに配置する。

## `nkaa/` 配下
- `framework/` : `BaseAgent`, `StandardManager`, チャンネル抽象など基盤クラス。
  - `channels/` : チャンネル本体、マネージャ、優先度キュー、永続化リポジトリの実装。
- `presets/`
  - `agents/` : 汎用的なエージェント実装（例: 標準入出力ベースの人間エージェント）。
  - `managers/` : プリセットマネージャ（例: `single_agent_model.py`）。
  - `tools/` : プリセットで利用するツールのダミー実装。
- `legacy/` : 旧研究用実装 (`legacy/research_agent_v1/`, `legacy/research_agent_v2/`) を格納。設計メモは `docs/legacy/` を参照。

## `docs/` 配下
- `concept.md` : 現行コンセプトと設計概要。
- `implementation_status.md` : 実装進捗チェックリスト。
- `plans/` : 具体的な実装計画や永続化プランを記録する場所（ExecPlan は `docs/workflows/` に保持）。
- `specs/` : 機能やチャネルなどの仕様ドキュメント（例: `specs/channel_spec.md`）。
- `guides/` : サンプル方針・ショートカット・運用ルールなどの手順書。
- `notes/` : 開発メモや調査ログ。試行中の知見をまとめる。
- `directory_structure.md` : 本ファイル。
- `meta_plan/` : テンプレートや横断計画メモ。
- `workflows/` : ワークフロー別ガイドライン（ExecPlan / ライブラリ知識共有 / ワークフロー追加手順など）。
- `legacy/` : 旧資料。
- `usage/` : コマンドチートシート。

## 今後の更新指針
- 重要ディレクトリを新設・削除した場合は内容を更新する。
- Docker 環境や追加ツールチェーンが整備されたら関連セクションを拡充する。
- legacy 資料を整理した場合は、本ドキュメントからも参照先を見直す。
