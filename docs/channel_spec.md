# チャンネル仕様ドキュメント

## 概要
チャネル機能はエージェント間のメッセージ交換を共通の抽象で扱うための仕組みです。本ドキュメントではチャネルに関連するコンポーネント、合意済みの仕様、今後残っている課題を整理します。

## コンポーネント構成

### ChannelManager (`nkaa/framework/channels/manager.py`)
- チャネル ID の発番とチャネルインスタンスの登録を担当する。
- エージェントの参加 (`join_agent`)・離脱 (`leave_agent`) を管理し、所属チャネル情報をリポジトリへ反映する。
- `search_channels` でチャネルメタデータを条件付きに列挙でき、エージェントの探索・購読フローに利用する。
- チャネル生成時に永続化用コールバック（`save_hook`）をチャネルへ渡し、チャネル単体での保存操作を可能にする。
- リポジトリからチャネル・メンバーシップ情報を復元して起動時状態を再構成する。
- 未読キューを扱うハンドラを外部から受け取り、離脱時に `attach_unread_handler` 経由で未読ポインタ破棄を委譲する。

### MessageManager (`nkaa/framework/message_manager.py`)
- メッセージ書き込み時に履歴を保存し、各エージェント専用キューへメッセージ ID と優先度を投入する（バックエンドは InMemory / SQL を自動選択）。
- `read_for_agent` で未読キューからポインタを取り出し、リポジトリからメッセージ本体を解決する。
- 未読スナップショット (`snapshot_unread_records`) を提供し、クラッシュ復旧向けのエクスポート／インポート処理を担う。
- エージェント離脱時に `discard_agent_channels` を用いて該当チャネルのポインタを破棄する。
- 送信先解決には `MessageRouteProvider` 抽象を利用する。既定では `ChannelMessageRouteProvider` を介して `ChannelManager` を適合させるが、将来的にチャネル以外のシステムメッセージ経路にも差し替え可能となる。

### ChannelTools (`nkaa/framework/tools.py`)
- エージェントが利用するチャネルメタデータ操作の窓口。
- `join/leave`・`search`・`join_matching` などの操作を `ChannelManager` に委譲する。
- `save_channel` によりチャネル単体の永続化をトリガーできる。
- `joined_channel_metadata()` により参加済みチャネルの `ChannelMetadata` を直接取得できる。プロンプト組み立てや UI 表示など、チャネル名と説明をエージェントへ渡す用途で活用する。
- メッセージ送受信は `MessageTools` に切り出しており、`ChannelTools` はチャネル管理機能に専念する。

### MessageTools (`nkaa/framework/tools.py`)
- メッセージの送受信・未読スナップショット保存を `MessageManager` 経由で提供するツール。
- `send/send_async` でチャネルへメッセージを投稿し、`read/read_async` で未読を取得する。
- `save()` で担当エージェントの未読キューをスナップショットとして永続化する（InMemory バックエンドのみ）。SQL バックエンドでは常時 DB に保存されるため no-op。
- 停止シグナル (`StopMessage`) を含めた協調停止を `read_async` で扱い、`stop_event` 連動によるキャンセルをサポートする。
- `fetch_message` / `fetch_messages` で既読メッセージをチャネル ID・メッセージ ID から再取得し、再起動後のコンテキスト復元などに活用できる。

### ChannelRepository (`nkaa/framework/channels/repository.py`)
- チャネルメタデータ、メッセージ履歴、未読レコード、所属情報を読み書きする抽象層。
- 既定では `InMemoryChannelRepository` を使用し、`SQLChannelRepository` を通じて PostgreSQL / SQLite などの永続化層へ差し替えられる。
- `persist_message` は永続層で採番した `message_id` を返却し、`ChannelManager` 側での未読管理に利用する。

### MessageQueue (`nkaa/framework/channels/queue.py`)
- 各エージェント専用の優先度付きキュー実装。InMemory バックエンドでは `MessageQueue` がそのまま利用され、SQL バックエンドでは `channel_unread` テーブルが永続キューとして機能する。
- キュー要素はメッセージ本体ではなく `AgentMessagePointer`（チャネル ID、メッセージ ID、優先度、投入時刻）であり、履歴取得はリポジトリ経由で行う。
- チャネルフィルタリング、未読スナップショット取得、チャネル離脱時の破棄操作をサポートする。SQL バックエンドでは `ORDER BY priority, enqueued_at, id` で取得し、取得と同時に行を削除する。

## 決定済みの仕様
- メッセージ履歴はデータベース（PostgreSQL を想定）に保存し、チャネル本体は `ChannelRepository` を通じて永続化操作を行う。
- `ChannelMessage.payload` には JSON など構造化データを保持できる。永続層でのシリアライズ形式はリポジトリ実装が担う。
- `MessageManager.snapshot_unread_records()` で未読キューのスナップショットを取得し、永続化はリポジトリやエージェント側の責務として扱う。
- チャネル ID は `channel_{n}` 形式で発番し、外部指定は今後の拡張とする。
- InMemory リポジトリを用いた動作確認では、後述のサンプルコードのように `ChannelManager` / `MessageManager` と `ChannelTools` / `MessageTools` を組み合わせて基本的な送受信と復元フローを確認できる。

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
from nkaa.framework.channels import (
    ChannelManager,
    ChannelMessageRouteProvider,
    DatabaseChannelConfig,
    InMemoryChannelRepository,
)
from nkaa.framework.message_manager import MessageManager
from nkaa.framework.tools import ChannelTools, MessageTools

repository = InMemoryChannelRepository()
channel_manager = ChannelManager(repository)
route_provider = ChannelMessageRouteProvider(channel_manager)
message_manager = MessageManager(repository, route_provider)
channel_manager.attach_unread_handler(message_manager)
channel = channel_manager.create(DatabaseChannelConfig(name="demo"))

alice_channels = ChannelTools(agent_id="alice", manager=channel_manager)
bob_channels = ChannelTools(agent_id="bob", manager=channel_manager)
alice_messages = MessageTools(agent_id="alice", manager=message_manager)
bob_messages = MessageTools(agent_id="bob", manager=message_manager)

alice_channels.join(channel.id)
bob_channels.join(channel.id)

alice_messages.send(channel.id, {"text": "こんにちは"})
message = bob_messages.read()
print("Bob received:", message.payload if message else None)

# エージェントごとに未読スナップショットを永続化
alice_messages.save()
bob_messages.save()

restored_channel_manager = ChannelManager(repository)
restored_route_provider = ChannelMessageRouteProvider(restored_channel_manager)
restored_message_manager = MessageManager(repository, restored_route_provider)
restored_channel_manager.attach_unread_handler(restored_message_manager)
restored_message = restored_message_manager.read_for_agent("bob")
print("Restored unread:", restored_message.payload if restored_message else None)
```

## 関連資料
- [docs/channel_persistence_plan.md](./channel_persistence_plan.md) : PostgreSQL を用いた永続化設計案。
- [docs/implementation_status.md](./implementation_status.md) : チャネル実装に関する進捗と残タスク。
- `tests/framework/test_channels.py` : InMemory 実装でチャネルの送受信や復元を確認するテスト。
