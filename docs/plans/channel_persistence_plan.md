# チャンネル永続化方針（PostgreSQL + Docker Compose）

> **更新**: SQLAlchemy を利用した `SQLChannelRepository` を `src/nkaa/framework/channels/repository.py` に追加し、PostgreSQL / SQLite を含む RDBMS 上でチャネル履歴と未読情報を扱えるようになりました。本ドキュメントの設計方針は継続的な改善タスク（一括キュー処理や Docker Compose 化など）を整理する目的で維持しています。

## ゴール
- チャンネルのプライマリキューを PostgreSQL / SQLite の `channel_unread` テーブルで運用し、優先度と投入時刻に `id` を加えた安定ソートでデキューできるようにする（実装済み: `SQLMessageQueueBackend`）。
- Python からは SQLAlchemy Core/ORM を用い、PostgreSQL では `SELECT ... FOR UPDATE SKIP LOCKED`、SQLite では楽観的ロックで取り出し → `DELETE` する方式を採用する。
- Docker Compose でデータベース環境を再現し、`.env` から読み込む環境変数でホスト側ディレクトリやポート番号を設定できるようにする（Docker Volume は使用しない）。

## データモデルの基本設計
- `channel_messages` テーブル  
  - 主キー: `(channel_id TEXT, message_id INTEGER)`（チャネル内で単調増加）  
  - カラム: `sender_id TEXT`, `payload JSONB`, `metadata_json JSONB`, `priority INTEGER`, `created_at TIMESTAMPTZ DEFAULT now()`  
  - チャネルごとの `message_id` 採番は `SQLChannelRepository.persist_message` が担当。
- `channel_unread` テーブル  
  - カラム: `id SERIAL PRIMARY KEY`, `agent_id TEXT`, `channel_id TEXT`, `message_id INTEGER`, `priority INTEGER`, `enqueued_at TIMESTAMPTZ DEFAULT now()`  
  - インデックス: `(agent_id, priority, enqueued_at, id)`（ORM 側で `ORDER BY` して取得。実装では `ix_channel_unread_agent_priority_enqueued_id` として作成）。  
  - PostgreSQL では `FOR UPDATE SKIP LOCKED` を使い並列デキューを実現。SQLite は単一ワーカー想定で通常の `SELECT` → `DELETE` を行う。
- 期限前メッセージのスキップや可視性タイムアウトはアプリ層で制御し、再配信・デッドレター処理を今後の拡張ポイントとして残す。

## Docker ディレクトリ構成
```
docker/
  docker-compose.yml
  channel/
    Dockerfile
    init.sql        # 必要に応じて初期化スクリプトを配置
```
- `docker/channel/Dockerfile` は公式 `postgres:<version>` をベースイメージとし、ロケール設定や追加ツールがあればここに追記する。
- 初期テーブル作成を自動化したい場合は `init.sql` を配置し、`docker-compose.yml` 側で `/docker-entrypoint-initdb.d/` へコピーする。

## docker-compose.yml の要点
- サービス名には `nkaa-channel-db` を推奨し、`container_name` は環境変数 `NKAA_CONTAINER_PREFIX` を用いて `${NKAA_CONTAINER_PREFIX:-nkaa}-channel-db` の形式で制御する（デフォルトは `nkaa-channel-db` ）。
- `.env`（リポジトリにはコミットせず、`.gitignore` 済みとする）に以下の環境変数を記載し、Compose から参照する。
  - `NKAA_CONTAINER_PREFIX` : コンテナ名のプレフィックス（例: `nkaa`）
  - `NKAA_CHANNEL_DB_STORAGE` : ホスト上で永続化するディレクトリパス
  - `NKAA_CHANNEL_DB_PORT` : 公開ポート番号（例: 5433）
  - `NKAA_CHANNEL_DATABASE_URL` : アプリケーションから接続するための URL（例: `postgresql+psycopg://...`）
- `docker-compose.yml` では `${NKAA_CHANNEL_DB_STORAGE:-./_data/channel-db}` のようにデフォルト値を設定しつつ、`.env` があれば上書きされる構成にする。
- 例:
  ```yaml
  services:
    nkaa-channel-db:
      container_name: "${NKAA_CONTAINER_PREFIX:-nkaa}-channel-db"
      build: ./channel
      environment:
        POSTGRES_DB: nkaa
        POSTGRES_USER: nkaa
        POSTGRES_PASSWORD: nkaa
      volumes:
        - "${NKAA_CHANNEL_DB_STORAGE:-./_data/channel-db}:/var/lib/postgresql/data"
      ports:
        - "${NKAA_CHANNEL_DB_PORT:-5433}:5432"
  ```
- 共有が必要な値は `.env.example` に記載し、利用者はコピーして `.env` を作成する運用とする。

## Python 実装メモ
- `MessageManager` はバックエンド抽象を導入し、SQL リポジトリを検出した場合は `SQLMessageQueueBackend` を自動選択して `channel_unread` テーブルへ直接 enqueue/dequeue する。InMemory 構成では `MessageQueue` ベースのバックエンドが従来どおり使用される。
- SQL バックエンドは SQLAlchemy Core を用い、`select(...).order_by(priority, enqueued_at, id)` で取得後に `delete` する。PostgreSQL のみ `with_for_update(skip_locked=True)` を付与。
- DB バックエンドでは `MessageTools.save()` が no-op（常時永続化済み）となり、InMemory のみ既存のスナップショット保存を継続する。
- 接続文字列は環境変数（例: `NKAA_CHANNEL_DATABASE_URL`）にまとめ、Docker Compose のサービス名をホスト名として指定する。
- 将来的なバックアップやメンテナンス向けに、`VACUUM` / `REINDEX` / バッチ削除タスクをスケジュールできるよう、メンテナンスコマンドのプレイブックを別途整備する。

## 次のステップ案
1. `docker/channel/Dockerfile` と `docker/docker-compose.yml` を上記方針で初期化。必要なら Make タスクに `docker compose up nkaa-channel-db` を追加。
2. `src/nkaa/framework/channel.py` を PostgreSQL バックエンド対応へ拡張し、`ChannelManager` から永続化層を呼び出す。
3. pytest でデータベースを用いたキュー操作のテストを整備し（例: docker-compose で立ち上げた DB を前提に pytest fixture を作成）、優先度順・再取得・並列動作を確認する。
