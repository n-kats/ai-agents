# ExecPlan: データベース駆動のメッセージ基盤

## 目的と意図
- 目的: [README_dev.md](../README_dev.md) で構想されているチャネル／メッセージの仕組みを、インメモリ依存から脱却してデータベース上で永続化できる状態に引き上げる。
- ユーザー価値: エージェント間のやり取りをプロセス再起動後も復元でき、将来的な水平スケールや監査ログ出力の土台になる。
- 確認方法: SQLite（インメモリ）および PostgreSQL を対象に `pytest tests/framework/test_channels.py -k database` などのテストセットを通し、DB バックエンドで送受信・未読復元が可能であることを確認する。

## 状況と前提整理
- レポジトリの現状: `ChannelRepository` 抽象はあるが、実際の `MessageQueue` は `src/nkaa/framework/channels/queue.py` にあるインメモリ実装のみで、[README_dev.md](../README_dev.md) が言及する DB ベースのメッセージストアは未整備。`SQLChannelRepository` は履歴保存と未読スナップショット置換を提供するだけで、リアルタイムの enqueue/dequeue はプロセス内に留まっている。
- 主要ファイル/モジュール:
  - `src/nkaa/framework/channels/repository.py`: チャネルメタデータとメッセージ履歴の永続化ロジック。
  - `src/nkaa/framework/message_manager.py`: メッセージ配送および未読キュー制御。
  - `src/nkaa/framework/channels/queue.py`: 受信者ごとの優先度付きキュー（現在はプロセス内メモリのみ）。
  - [docs/plans/channel_persistence_plan.md](./channel_persistence_plan.md), [README_dev.md](../README_dev.md): DB を使ったメッセージ基盤の構想を記載。
- 用語定義:
  - **メッセージストア**: チャネル単位の履歴と未読キューを永続化する DB 層。
  - **未読ポインタ**: 受信すべきメッセージをエージェント × チャネル × message_id で指し示す行。
  - **キューマネージャ**: 未読ポインタを取得／削除する API を提供する層（現状は `MessageManager` が役割を兼任）。

## 作業計画
1. **データモデル設計**  
   - 既存の `channel_messages`（主キー: `channel_id`, `message_id`）と `channel_unread`（`id`, `agent_id`, `channel_id`, `message_id`, `priority`, `enqueued_at`）をベースに、未読管理を常時 DB へ書き込む前提へ更新する。  
   - `channel_unread` の並び順は `priority` → `enqueued_at` → `id` で安定化し、PostgreSQL では `FOR UPDATE SKIP LOCKED` により並列デキュー時のスターブを防ぐ。  
   - エージェント単位の走査を高速化するため、`(agent_id, priority, enqueued_at, id)` の複合インデックスを作成してソート順と一致させる。  
   - 既存 `channel_channels` / `channel_memberships` との関係、および `MessageManager` から参照する API を ExecPlan 内で整理する。
2. **永続化層の抽象と実装**  
   - `MessageManager` にバックエンド抽象を導入し、`InMemoryMessageQueueBackend`（従来の `MessageQueue` を内蔵）と `SQLMessageQueueBackend`（`channel_unread` を直接操作）を実装する。  
   - SQL バックエンドは SQLAlchemy Core を用い、PostgreSQL では `with_for_update(skip_locked=True)`、SQLite では通常の `SELECT` → `DELETE` を採用する。  
   - `SQLChannelRepository` は履歴保存と `channel_unread` のテーブル作成を担い、バックエンド選択時にエンジンを受け渡す。
3. **メッセージマネージャの差し替え**  
   - `MessageManager` に `queue_backend`（デフォルトは in-memory）引数を追加し、`write()` で `MessageStoreBackend.enqueue_unread()` を呼び出すように変更する。  
   - `read_for_agent()` ではバックエンドの `dequeue_unread()` を利用して DB 内の未読ポインタを一貫して取り出す。`allowed_channels` フィルタは SQL 側に渡し、残キューをメモリにため込まない。  
   - 既存の `MessageQueue` は `InMemoryMessageStoreBackend` の内部実装として再利用し、テストやライトウェイト環境での挙動を維持する。
   - 履歴再参照を支援するため、`MessageManager`／`MessageTools` にチャネル ID・メッセージ ID から履歴を読み直す API を追加する。
4. **テスト整備**  
   - `tests/framework/test_channels.py` に `@pytest.mark.parametrize("backend_type", ["memory", "sqlite"])` のような切り替えを導入し、DB バックエンド時に `MessageManager` へ `SQLMessageStoreBackend` を注入する経路を検証する。  
   - デキュー順序（priority → enqueued_at → id）、チャネル離脱時の未読削除、未読スナップショット再構築（`MessageManager.snapshot_unread_records` が DB バックエンドでも矛盾しない）をテストケースとして増補する。
5. **ドキュメント/進捗更新**  
   - `README_dev.md` の「チャンネル」セクションに新しいテーブル構成と `MessageStoreBackend` の概念図を追加し、実装済みの操作フロー（送信→永続化→未読登録→受信→削除）を箇条書きで説明する。  
   - [docs/plans/channel_persistence_plan.md](./channel_persistence_plan.md) の「データモデル」「Python 実装メモ」を今回の実装と一致させ、[docs/implementation_status.md](../implementation_status.md) の該当チェックリストに進捗を記録する。

## 具体的な作業手順
```bash
# 0. 依存関係を同期
UV_PROJECT_ENVIRONMENT=_tmp/codex_venv uv sync --group dev

# 1. 現状調査
rg -n "MessageQueue" -g"*.py"
rg -n "snapshot_unread" -g"*.py"

# 2. SQLite バックエンドで新実装を動作確認
UV_PROJECT_ENVIRONMENT=_tmp/codex_venv uv run pytest tests/framework/test_channels.py -k sqlite

# 3. フォールバック（インメモリ）も回帰確認
UV_PROJECT_ENVIRONMENT=_tmp/codex_venv uv run pytest tests/framework/test_channels.py -k memory
```

## 検証と受け入れ条件
- SQLite で `pytest tests/framework/test_channels.py -k database` がパスし、メッセージ送受信・未読復元が DB バックエンドでも機能すること。
- In-memory バックエンドを用いた既存テストが退行しないこと（`pytest tests/framework/test_channels.py -k memory`）。
- README_dev.md と `docs/plans/channel_persistence_plan.md` に記載した設計と実装が整合していることをレビューで確認する。

## 再実行性と復旧手順
- SQLAlchemy の `create_all` を利用してテーブルを毎回再構築できるようにし、`StaticPool` を使った in-memory SQLite で deterministic な再現を担保する。
- 破壊的マイグレーションが必要になった場合は `alembic` などの導入検討を TODO として ExecPlan に追記する。

## 成果物と補足
> - SQLAlchemy モデル（`channel_messages`, `channel_unread` 等）  
> - `MessageManager` のバックエンド切り替え実装  
> - DB バックエンド向けの pytest 追加（`allowed_channels` フィルタ挙動もカバー）  
> - `channel_unread` の複合インデックス `ix_channel_unread_agent_priority_enqueued_id`
> - `MessageTools.fetch_message(s)` による既読履歴の再取得

## インターフェースと依存関係
- 追加予定 API: `MessageManager` に `backend` or `queue_strategy` 引数を追加し、DB／メモリを選べるようにする。
- 依存ライブラリ: 既存の SQLAlchemy を継続利用。PostgreSQL 接続用に `psycopg[binary]` が必要な場合は `pyproject.toml` の optional dependency として整理。

## 意思決定ログ
- 判断: メッセージ未読キューを DB へ直接保存する  
  理由: README_dev.md が要求する「DB を使ったメッセージ仕組み」を満たすため、スナップショットではなく常時永続化する必要がある。  
  日付・担当: 2025-10-26 / Codex (GPT-5)
- 判断: 既存 in-memory キューは互換用に残す  
  理由: 軽量テストと既存サンプルを壊さず、DB が使えない環境でも利用可能にするため。  
  日付・担当: 2025-10-26 / Codex (GPT-5)
- 判断: `channel_unread` へ複合インデックスを付与する  
  理由: allowed_channels フィルタ適用時に `agent_id` 起点での検索性能と安定ソートを揃え、SQL バックエンドの読み出しを高速化するため。  
  日付・担当: 2025-10-27 / Codex (GPT-5)

## 結果と振り返り
- 成果: `MessageManager` にバックエンド抽象を導入し、`SQLChannelRepository` 利用時は `SQLMessageQueueBackend` が自動で選択されるようになった。pytest（`tests/framework/test_channels.py`）でインメモリ／SQLite 両方を通し、DB 再起動後も未読が復元されることを確認済み。  
- 課題: Docker Compose での実行例と Postgres での負荷検証は未整備。可視性タイムアウトやデッドレター行きの扱いも今後の検討事項。  
- 補足: allowed_channels フィルタの回帰テストと `channel_unread` の複合インデックスを追加し、SQL バックエンドの安定性を検証済み。
- 補足: 既読後もチャネル履歴を参照できるよう `MessageTools.fetch_message(s)` を追加し、再起動時にメッセージをコンテキストへ取り込めるようにした。
- 次のアクション: メッセージペイロードのバージョニング戦略やバックプレッシャー制御を別タスクとして検討する。
