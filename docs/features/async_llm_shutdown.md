# LLM 呼び出しの非同期化と停止シーケンス刷新計画

Textual UI からの終了要求でマネージャを即時停止させたいが、従来は LLM 呼び出し待ちでエージェントスレッドがブロックし続けてしまう。ここでは、LLM 呼び出しを非同期化しつつ安全にキャンセル・保存・停止を行うための詳細計画と、実装済みの内容をまとめる。

## 現状の課題
- 旧実装の `DelegationLLMAgent.run` は同期ループで `MessageTools.read(block=True)` → LLM 呼び出し → 応答送信を行い、途中で停止イベントを受け取っても処理を中断できなかった。
- `LLMCallTool` にはキャンセル手段がなく、HTTP リクエストの完了を待つしかない。
- チャネル関連コンポーネントは同期キュー (`queue.PriorityQueue`) を前提にした構成で、`ChannelManager` / `MessageManager` から `MessageTools` へ非同期インターフェースを提供できていない。
- ログ・履歴（`AgentLogTool`、`StdIOHumanHistory`）はスレッドからのアクセスを想定しているため、非同期タスク対応時に排他制御を見直す必要がある。

## 目標
1. LLM 呼び出し中でも停止イベントを受け次第キャンセルし、最小限の状態保存を行ってからエージェントを終了できるようにする。
2. Textual UI（human エージェント）が `/quit` やウィンドウ閉鎖で停止指示を出した際に、バックエンドのマネージャ／エージェントが確実に終了する。
3. 将来的なマルチエージェント拡張でも共通に利用できる `asyncio` ベースのチャネル／ツール API を整備する。

## 実装状況（最新）

- `StandardManager.run()` は `asyncio.run(self.run_async())` を呼び出す薄いラッパーになり、非同期版では停止イベントを `asyncio.to_thread` で監視したうえで `tools.stop()`・`agent.stop()`・`join()` をシーケンシャルに実行する。
- `MessageTools` に `read_async` / `send_async` を追加し、`asyncio.to_thread` + ポーリングタイムアウトでブロック読み取りをラップ。キャンセル時は `stop_event` を参照して即座に停止シグナル (`StopMessage`) を返す。
- メッセージ配送責務を `MessageManager` へ分離し、`ChannelManager` はチャネルメタデータとメンバーシップの管理に注力できるようにした。離脱時は `MessageManager.discard_agent_channels()` を介して未読ポインタを破棄する。
- `LLMCallTool` に `acreate_response` / `call_parsed_async` など複数の `async` API を追加し、OpenAI SDK の `AsyncOpenAI` を利用したキャンセル可能な呼び出しを実現。同期メソッドは従来どおり `OpenAI` クライアントを使用し互換性を維持。
- `DelegationLLMAgent` は `run_async` を新設し、`asyncio.create_task` で LLM 呼び出しを追跡しつつ `/quit` による `stop()` シグナルで未完了タスクを `cancel()` する。`invoke_structured_llm` も `async def` 化してログと例外ハンドリングを整理した。
- `DelegationLLMAgent` の `shutdown_grace_period` を撤廃し、停止時は即座に LLM タスクへキャンセルを伝搬するのみとした。
- `tests/samples/test_llm_delegation_shutdown.py` を追加し、擬似 LLM を用いた停止時の即時キャンセル動作を回帰テスト化した。
- `tests/framework/test_channels.py` に非同期 API のラウンドトリップ検証を追加し、最低限の回帰テストを整備した。

今後は UI 経由の統合キャンセル挙動や、`MultiprocessingManagerExecutionBackend` との整合性検証を継続する。

## 実装ステップ（更新版）

### 1. `MessageManager` / `MessageTools` の非同期 API 整備
- 既存の優先度キューは維持しつつ、`MessageTools.read_async()` で `asyncio.to_thread` + タイムアウトポーリングを実装。キャンセル時に `stop_event` を参照し、同期待ちから抜けられるようにした。
- 書き込みについても `MessageTools.send_async()` を追加し、ブロッキング I/O をイベントループ外へ逃がす。
- 未読スナップショットは同期処理のままとし、`MessageTools.save()` で整合性を担保する（必要に応じて将来 `asyncio.Lock` を導入）。

### 2. マネージャーとエージェントの実行パターン見直し
- `StandardManager.run_async()` を実装し、停止イベント待機・ツール停止・エージェント停止・`join()`・`save()` を順序付けた。`run()` は `asyncio.run` で包んだ互換ラッパー。
- エージェント側は `run_async()` を持つ場合に優先実行され、同期エージェントは従来どおり `run()` が呼ばれる。
- `DelegationLLMAgent` は `run_async()` を実装し、停止要求時に `asyncio.Task.cancel()`・`asyncio.gather(..., return_exceptions=True)` を介して未完了 LLM 呼び出しを安全に中断するよう更新した。

### 3. `LLMCallTool` のキャンセル対応
- `AsyncOpenAI` クライアントを lazily 初期化し、`acreate_response`・`call_parsed_async` など非同期 API を整備。キャンセル時は `asyncio.CancelledError` をそのまま伝播させ、呼び出し元でログを出せるようにした。
- 同期 API は従来どおり `OpenAI` クライアントを利用し、既存コードとの互換性を維持。

### 4. 共有リソースの排他制御と保存
- ログツールは従来どおり同期ロガーを利用し、`DelegationLLMAgent` 側で停止シグナルを受けた段階で LLM タスクをキャンセル → `MessageTools.save()` → `manager.save()` を順序付けた。さらに詳細な排他制御や UI 側テストは今後の課題とする。

### 5. テスト戦略
- `tests/framework/test_channels.py` に `asyncio.run` ベースの非同期テストを追加済み。
- キャンセルに応答しない LLM 呼び出しに対する停止挙動は `tests/samples/test_llm_delegation_shutdown.py` で検証する。UI 経由の統合テストは未着手。

## 未決事項
- `asyncio` 化はプロセス実行バックエンド（`MultiprocessingManagerExecutionBackend`）と整合するのか？ プロセス実行が必要な場合の設計を別途検討する。
- OpenAI SDK の非同期 API 利用時に追加依存が発生するか、既存のランタイム環境でサポートされているかの確認。
- キャンセル後に中断された対話をどこまで履歴に残すか、UI 表示の仕様（ユーザへの通知方法）を検討する。

## アクションアイテム
- [x] `MessageTools.read_async` / `send_async` を追加し、非同期ユニットテストを整備した。
- [x] `DelegationLLMAgent.run_async` と `LLMCallTool` の async API を実装し、サンプルでの動作を移行した。
- [ ] Textual UI からの停止要求で `asyncio` タスクキャンセルが期待通り伝播する統合テストを整備する。
- [x] ドキュメント（本ページおよび [docs/implementation_status.md](../implementation_status.md)）へ設計意図と進捗を記録した。
