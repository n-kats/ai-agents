# LLM 呼び出しの非同期化と停止シーケンス刷新計画

Textual UI からの終了要求でマネージャを即時停止させたいが、現状は LLM 呼び出し待ちでエージェントスレッドがブロックし続けてしまう。ここでは、LLM 呼び出しを非同期化しつつ安全にキャンセル・保存・停止を行うための詳細計画をまとめる。

## 現状の課題
- `DelegationLLMAgent.run` は同期ループで `ChannelTools.read(block=True)` → LLM 呼び出し → 応答送信を行い、途中で停止イベントを受け取っても処理を中断できない。
- `LLMCallTool` にはキャンセル手段がなく、HTTP リクエストの完了を待つしかない。
- `ChannelManager` / `ChannelTools` は同期キュー (`queue.PriorityQueue`) を前提にした実装のため、`asyncio` ベースの分岐を追加する余地がない。
- ログ・履歴（`AgentLogTool`, `StdIOHumanHistory`）はスレッドからのアクセスを想定しているため、非同期タスク対応時に排他制御を見直す必要がある。

## 目標
1. LLM 呼び出し中でも停止イベントを受け次第キャンセルし、最小限の状態保存を行ってからエージェントを終了できるようにする。
2. Textual UI（human エージェント）が `/quit` やウィンドウ閉鎖で停止指示を出した際に、バックエンドのマネージャ／エージェントが確実に終了する。
3. 将来的なマルチエージェント拡張でも共通に利用できる `asyncio` ベースのチャネル／ツール API を整備する。

## 実装ステップ

### 1. `ChannelManager` / `ChannelTools` の非同期 API 整備
- `ChannelManager` に `async_read_for_agent` / `async_write` など `asyncio` 対応メソッドを追加する。
- 内部キューは `asyncio.PriorityQueue` へ移行し、既存の同期 API との後方互換を保つラッパーを用意する。
- 未読スナップショット保存やメンバーシップ操作でデータ競合が起きないよう、`asyncio.Lock` または `contextlib.AsyncExitStack` を活用した排他制御ポリシーを定義する。

### 2. マネージャーとエージェントの実行パターン見直し
- `StandardManager`（もしくはプリセットのマネージャー）に `async def run_async()` を追加し、実行キューのポーリング・停止シグナル処理・エージェントタスク管理をイベントループ主体で行う。
- 既存の `run()` による互換運用は必須としない。必要な場合は `run()` から `asyncio.run(run_async())` を呼び出す薄いラッパーを提供する。
- スレッド／プロセス構成は維持する想定とし、各ワーカーが専用のイベントループを持ち `loop.run_until_complete(agent.run_async(...))` で実務処理を行う。これにより、マルチスレッドをやめずに非同期化を取り込める。
- `DelegationLLMAgent` などエージェント実装は `async def run_async(...)` を新設し、チャネル読み取り・LLM 呼び出し・結果送信を `await` で繋ぐ。停止要求受信時はタスクキャンセル → 状態保存 → ループ停止の順でシーケンスを管理する。

### 3. `LLMCallTool` のキャンセル対応
- OpenAI SDK を `async` 版で利用し、`await client.responses.create(...)` の形で呼び出す。
- タスクキャンセルが入った場合に HTTP リクエストがクリーンに終わるよう、`asyncio.timeout` / `asyncio.CancelledError` を捕捉し、中断時のログと後処理（未送信メッセージの保存など）を明示する。
- 非同期呼び出しと同期呼び出し API の両立が必要であれば、同期版は内部で `asyncio.run` / `loop.run_until_complete` を用いて再利用する設計にする。

### 4. 共有リソースの排他制御と保存
- ログ (`AgentLogTool`)・履歴 (`StdIOHumanHistory`) などは `asyncio.to_thread` で同期処理に落として呼び出すか、`asyncio.Lock` を用いてデータ競合を防ぐ。
- Textual UI からの停止指示時は「チャネル履歴保存 → ログ flush → タスクキャンセル」の順に行えるよう、明示的な停止シーケンスをドキュメント化する。

### 5. テスト戦略
- `pytest-asyncio` を導入し、停止イベント発火後に LLM 呼び出しタスクがキャンセルされることを確認する非同期テストを追加する。
- チャネルキューがキャンセル後にクリーンな状態へ戻ること、未読記録が矛盾しないことをユニットテストで保障する。
- Textual UI をモックして `/quit` → `stop_event_tool` → 全エージェント終了をシナリオテストする。

## 未決事項
- `asyncio` 化はプロセス実行バックエンド（`MultiprocessingManagerExecutionBackend`）と整合するのか？ プロセス実行が必要な場合の設計を別途検討する。
- OpenAI SDK の非同期 API 利用時に追加依存が発生するか、既存のランタイム環境でサポートされているかの確認。
- キャンセル後に中断された対話をどこまで履歴に残すか、UI 表示の仕様（ユーザへの通知方法）を検討する。

## アクションアイテム
1. `ChannelManager` に `asyncio` 対応メソッドを実装し、既存テストを通しつつ非同期テストを追加する。
2. `DelegationLLMAgent` / `LLMCallTool` を非同期実装へ移行し、同期ラッパーの互換性テストを実施する。
3. Textual UI からの停止要求で `asyncio` タスクキャンセルが期待通り伝播する統合テストを整備する。
4. ドキュメント（本ページおよび `docs/concept.md`）に停止シーケンスとキャンセル仕様を追記し、利用者への影響を明確化する。
