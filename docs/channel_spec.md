# チャンネル仕様ドキュメント

## 概要
チャネル機能はエージェント間のメッセージ交換を共通の抽象で扱うための仕組みです。本ドキュメントではチャネルに関連するコンポーネント、合意済みの仕様、今後残っている課題を整理します。

## コンポーネント構成

### ChannelManager (`nkaa/framework/channels/manager.py`)
- チャネル ID の発番とチャネルインスタンスの登録を担当する。
- エージェントの参加 (`join_agent`)・離脱 (`leave_agent`) を管理し、所属チャネルごとの未読キューを更新する。
- メッセージ書き込み時に履歴を保存し、各エージェント専用キューへメッセージ ID と優先度を投入する。
- `search_channels` でチャネルメタデータを条件付きに列挙でき、エージェントの探索・購読フローに利用する。
- チャネル生成時に永続化用コールバック（`save_hook`）をチャネルへ渡し、チャネル単体での保存操作を可能にする。
- リポジトリからチャネル・未読情報を復元して起動時状態を再構成する。
- `read_for_agent` は未読キューからメッセージを1件解決し、履歴リポジトリに問い合わせてメッセージ全体を返す。アプリケーション層からは `ChannelTools.read` を経由するのが基本方針で、直接呼び出すのはテストや復旧ユーティリティに限定する。

### ChannelTools (`nkaa/framework/tools.py`)
- エージェントが利用するチャネル操作の窓口。
- `join/leave/send/read` や `snapshot_unread`・`save_channel` を提供し、内部的に `ChannelManager` の API を呼び出す。
- `search` でメタデータ検索をラップし、`join_matching` で検索結果へ自動参加するユーティリティを提供する。
- `save()` で担当エージェントの未読キューをスナップショットとして永続化する。既存スナップショットから自身のレコードだけを差し替えるため、他エージェントの未読状態を維持できる。
- エージェント ID ごとに初期化され、初期化時に未読キュー登録を確実に行う。
- `read` はブロッキング／ノンブロッキングの切り替えだけを提供し、チャネル ID のフィルタリングやフォールバック判定はすべて `ChannelManager.read_for_agent` に任せる。アプリ側は `ChannelTools` を通じてのみ読み取ることで、一貫したアクセス制御とロギングを維持できる。
- `joined_channel_metadata()` により参加済みチャネルの `ChannelMetadata` を直接取得できる。プロンプト組み立てや UI 表示など、チャネル名と説明をエージェントへ渡す用途で活用する。

### ChannelRepository (`nkaa/framework/channels/repository.py`)
- チャネルメタデータ、メッセージ履歴、未読レコード、所属情報を読み書きする抽象層。
- 既定では `InMemoryChannelRepository` を使用し、`SQLChannelRepository` を通じて PostgreSQL / SQLite などの永続化層へ差し替えられる。
- `persist_message` は永続層で採番した `message_id` を返却し、`ChannelManager` 側での未読管理に利用する。

### MessageQueue (`nkaa/framework/channels/queue.py`)
- 各エージェント専用の優先度付きキュー実装。
- キュー要素はメッセージ本体ではなく `AgentMessagePointer`（チャネル ID、メッセージ ID、優先度、投入時刻）であり、履歴取得はリポジトリ経由で行う。
- チャネルフィルタリング、未読スナップショット取得、チャネル離脱時の破棄操作をサポートする。

## 決定済みの仕様
- メッセージ履歴はデータベース（PostgreSQL を想定）に保存し、チャネル本体は `ChannelRepository` を通じて永続化操作を行う。
- `ChannelMessage.payload` には JSON など構造化データを保持できる。永続層でのシリアライズ形式はリポジトリ実装が担う。
- `ChannelManager.snapshot_unread_records()` で未読キューのスナップショットを取得し、永続化はリポジトリやエージェント側の責務として扱う。
- チャネル ID は `channel_{n}` 形式で発番し、外部指定は今後の拡張とする。
- InMemory リポジトリを用いた動作確認では、後述のサンプルコードのように `ChannelManager` と `ChannelTools` を組み合わせて基本的な送受信と復元フローを確認できる。

## 未決事項・課題
- ~~**PostgreSQL 実装**~~: SQLAlchemy ベースの `SQLChannelRepository` としてチャネル履歴／未読スナップショットの永続化を実装済み（PostgreSQL, SQLite をサポート）。
- **チャネル探索 API**: エージェントが自律的にチャネルを探索・購読するための API 設計とアクセス制御が未定。
- **ペイロードスキーマ**: `ChannelMessage.payload` のバージョニングや検証ポリシーが未策定。後方互換性を含めた運用方針を定める必要がある。
- **スナップショット運用**: 未読スナップショットの取得・保存タイミングとクラッシュ復旧手順を整理する必要がある。
- **停止時の扱い**: エージェント削除時の未読キュー・所属情報の処理方針が未決。
- **テスト拡充**: PostgreSQL バックエンドや複数プロセスを想定した統合テスト戦略が今後の課題。

## InMemory を利用した動作例

以下は InMemory リポジトリを使ってチャネルを体験的に確認する最小コード例です。

```python
from nkaa.framework.channels import ChannelManager, DatabaseChannelConfig, InMemoryChannelRepository
from nkaa.framework.tools import ChannelTools

repository = InMemoryChannelRepository()
manager = ChannelManager(repository)
channel = manager.create(DatabaseChannelConfig(name="demo"))

alice = ChannelTools(agent_id="alice", manager=manager)
bob = ChannelTools(agent_id="bob", manager=manager)

alice.join(channel.id)
bob.join(channel.id)

alice.send(channel.id, {"text": "こんにちは"})
message = bob.read()
print("Bob received:", message.payload if message else None)

# エージェントごとに未読スナップショットを永続化
alice.save()
bob.save()

restored_manager = ChannelManager(repository)
restored_message = restored_manager.read_for_agent("bob")
print("Restored unread:", restored_message.payload if restored_message else None)
```

## 関連資料
- `docs/channel_persistence_plan.md` : PostgreSQL を用いた永続化設計案。
- `docs/implementation_status.md` : チャネル実装に関する進捗と残タスク。
- `tests/framework/test_channels.py` : InMemory 実装でチャネルの送受信や復元を確認するテスト。
