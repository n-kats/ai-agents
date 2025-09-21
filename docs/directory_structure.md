# Repository Directory Structure

このドキュメントは本リポジトリの主要ディレクトリと役割をまとめています。構成を更新した場合は、本ファイルもあわせて改訂してください。

## ルート直下
- `nkaa/` : フレームワーク本体。基盤コード、プリセット、旧研究用実装を含みます。
- `docs/` : 現行アーキテクチャや運用方針をまとめたドキュメント。
- `docs/legacy/` : 過去の Research Agent 系資料や振り返りログ。参照のみ。
- `docs/meta_plan/` : 共通ガイドラインやポリシー類。プロジェクト横断で再利用可能な内容を配置。
- `docs/usage/` : `make lint` などのコマンドリファレンス。
- `docker/` : Docker Compose など環境構築用ファイル（PostgreSQL チャンネル基盤を追加予定）。
- `Makefile`, `pyproject.toml`, `uv.lock` : ビルドと依存管理設定。
- `_cache/`, `_output/`, `_data/` : 実行時生成物やキャッシュ（必要に応じて作成）。

## `nkaa/` 配下
- `framework/` : `BaseAgent`, `StandardManager`, チャンネル抽象など基盤クラス。
- `presets/`
  - `managers/` : プリセットマネージャ（例: `single_agent_model.py`）。
  - `tools/` : プリセットで利用するツールのダミー実装。
- `research_agent_v1/`, `research_agent_v2/` : 旧研究用実装。設計メモは `docs/legacy/` を参照。

## `docs/` 配下
- `concept.md` : 現行コンセプトと設計概要。
- `implementation_status.md` : 実装進捗チェックリスト。
- `channel_persistence_plan.md` : PostgreSQL を用いたチャンネル永続化案。
- `directory_structure.md` : 本ファイル。
- `meta_plan/` : 共通ガイドライン。
- `legacy/` : 旧資料。
- `usage/` : コマンドチートシート。

## 今後の更新指針
- 重要ディレクトリを新設・削除した場合は内容を更新する。
- Docker 環境や追加ツールチェーンが整備されたら関連セクションを拡充する。
- legacy 資料を整理した場合は、本ドキュメントからも参照先を見直す。
