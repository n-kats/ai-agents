# チャンネル永続化方針（PostgreSQL + Docker Compose）

## ゴール
- チャンネルのプライマリキューを PostgreSQL で運用し、優先度とタイムスタンプを複合キーとして安定ソートする。
- Python からは SQLAlchemy あるいは pgmq などのライブラリを用い、`ORDER BY priority, scheduled_at, id` と `FOR UPDATE SKIP LOCKED` を活用した並列デキューを実現する。
- Docker Compose でデータベース環境を再現し、`.env` から読み込む環境変数でホスト側ディレクトリやポート番号を設定できるようにする（Docker Volume は使用しない）。

## データモデルの基本設計
- テーブル名 `channel_messages`（想定）に以下の主なカラムを定義する:
  - `id SERIAL PRIMARY KEY`
  - `channel_name TEXT`
  - `priority INTEGER`
  - `scheduled_at TIMESTAMPTZ`
  - `payload JSONB`
  - `state SMALLINT`（0: ready, 1: processing, 2: done など）
  - `created_at TIMESTAMPTZ DEFAULT now()`
- 複合インデックス `CREATE INDEX idx_channel_priority_sched ON channel_messages(priority, scheduled_at, id);` を付与し、優先度→タイムスタンプ→シーケンス順で取得できるようにする。
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
- SQLAlchemy Core / ORM を推奨。`select(...).order_by(priority, scheduled_at, id).with_for_update(skip_locked=True)` で複数ワーカー対応のデキューが可能。
- 軽量ラッパとして `pgmq` を採用する場合でも、優先度・タイムスタンプ列はそのまま保持し、複合インデックスを付与する。
- 接続文字列は環境変数（例: `NKAA_CHANNEL_DATABASE_URL`）にまとめ、Docker Compose のサービス名をホスト名として指定する。
- 将来的なバックアップやメンテナンス向けに、`VACUUM` / `REINDEX` / バッチ削除タスクをスケジュールできるよう、メンテナンスコマンドのプレイブックを別途整備する。

## 次のステップ案
1. `docker/channel/Dockerfile` と `docker/docker-compose.yml` を上記方針で初期化。必要なら Make タスクに `docker compose up nkaa-channel-db` を追加。
2. `nkaa/framework/channel.py` を PostgreSQL バックエンド対応へ拡張し、`ChannelManager` から永続化層を呼び出す。
3. pytest でデータベースを用いたキュー操作のテストを整備し（例: docker-compose で立ち上げた DB を前提に pytest fixture を作成）、優先度順・再取得・並列動作を確認する。
