# 実装進捗チェックリスト

## フレームワークコア
- [x] 基底抽象を整備
  - `BaseAgent` / `BaseTools` / `BaseManager`
  - `src/nkaa/framework/agent.py`
- [x] `AgentConfig.build()` を抽象メソッド化
  - サブクラス実装を必須化
- [x] `StandardManager._load_agent()` のロード手順を統一
  - 設定ファイル -> `AgentConfig` 派生クラス検証
  - `build()` 実行 -> エージェント生成
- [x] `StandardManager` 実行バックエンド切替
  - 既定: `MultiprocessingManagerExecutionBackend`
  - 制約環境: `ThreadingManagerExecutionBackend`
- [x] `StandardManagerConfig.build_tools()` を追加
  - 共有ツール構築を設定側へ集約
- [x] `JsonLinesStateMixin` による状態永続化
  - `src/nkaa/framework/persistence.py`
  - `src/nkaa/presets/managers/single_agent_model.py`
- [x] `StandardManager.get_agent()` を追加
  - ID からエージェントを直接取得
- [x] loguru ベースのログ基盤
  - `configure_logging` / `LogBufferSink` / `LogStream`
  - `AgentLogTool` / `LogPanelAdapter`

## チャネルとメッセージ
- [x] チャネル関連を専用パッケージへ再編
  - `src/nkaa/framework/channels/`
  - `src/nkaa/framework/tools.py`
  - `ChannelManager` / `ChannelTools` / キュー / リポジトリの責務分離
- [x] `SQLChannelRepository` を追加
  - PostgreSQL / SQLite 対応
  - 履歴テーブル
  - 未読テーブル
  - `save()` ベースのスナップショット永続化（[docs/plans/exec_plan_message_database.md](./plans/exec_plan_message_database.md)）
- [x] `ChannelTools.joined_channel_metadata()` で参加チャネルのメタデータ取得を簡素化
- [ ] エージェント主体のチャネル検索 / 購読 API
  - [x] `ChannelSearchQuery`
  - [x] `ChannelManager.search_channels`
  - [x] `ChannelTools.search`
  - [x] `ChannelTools.join_matching`
- [ ] メッセージペイロードのバージョニングと検証
- [ ] `MessageManager.snapshot_unread_records()` を用いた未読スナップショット運用
- [x] `ChannelTools` / `MessageTools` を役割分離
  - `StopMessage` 受信を `MessageTools.read_async()` へ一本化
- [x] メッセージ配送と未読キュー管理を `MessageManager` として独立
  - `ChannelManager.leave_agent()` -> `MessageManager` 経由で未読ポインタ破棄
- [x] `MessageRouteProvider` 抽象を導入
  - 標準は `ChannelMessageRouteProvider`
- [x] 未読キューを常時永続化
  - `channel_unread` 複合インデックス（`agent_id`, `priority`, `enqueued_at`, `id`）
  - `allowed_channels` フィルタの回帰テスト
  - `MessageTools.fetch_message(s)` による履歴再取得
- [x] `MessageManager.list_channel_messages()` / `MessageTools.list_channel_messages()` でチャネル全体履歴を参照可能
- [ ] Opik クラウド連携と Langfuse 連携手段（優先度: 低）

## ツールとアダプター
- [x] アダプター経由でエージェントへツールを注入
  - `src/nkaa/framework/agent.py`
- [x] `ChannelTools` の雛形を整備
  - 複数チャネル操作を一元化
  - `src/nkaa/framework/tools.py`
- [x] `LLMCallTool` の対話型検証サンプル
  - `samples/llm_call_tool_interactive.py`
- [ ] ツール / アダプターの高度な利用例
  - アクセス制御
  - 永続化チャネル連携
- [ ] `HumanInteractionAgent`（CLI / GUI 共通）の設計とプリセット
  - [x] Textual ベースの人間エージェント
    - `src/nkaa/presets/agents/textual_human.py`
  - [x] 非メインスレッド実行時のシグナル登録エラー回避
  - [x] `LogPanelAdapter` 連携
    - チャット / ログのタブ切り替え
    - レベル / エージェント / チャネル絞り込み
  - [x] UI 終了後の `stop_manager` 発火
  - [x] `RichLog` 優先利用で長文折り返し

## 非同期実行と停止制御
- [x] LLM 呼び出しの非同期化
  - `ChannelManager` / `MessageTools` の asyncio 対応
  - `StandardManager.run_async()`（`run()` は互換ラッパー）
  - `DelegationLLMAgent.run_async()` で受信 -> LLM 呼び出し -> 送信を await 連結
- [x] 非同期コンテキストでの停止制御
  - `LLMCallTool` のキャンセル可能リクエスト
    - タイムアウト
    - キャンセルハンドラ
  - 排他制御ガイド（`asyncio.Lock`）
  - `shutdown_grace_period` 撤廃
  - 擬似 LLM による停止回避テスト（`tests/samples/test_llm_delegation_shutdown.py`）
  - `StopMessage` と `MessageTools.read_async()` による協調停止
- [ ] [docs/plans/async_llm_shutdown.md](./plans/async_llm_shutdown.md) に残る継続タスク

## プリセット
- [x] シングルエージェントプリセットとツール束ね（`src/nkaa/presets/managers/single_agent_model.py`）
- [x] `SimpleAgentConfig.build()` が自身を渡して `SingleAgent` を構築
- [x] `LLMCallTool` を GPT-5 系 Responses API 対応へ移行（`src/nkaa/presets/tools/llm_tool.py`）
- [ ] `InputTool` はダミー実装のまま（実運用向けツール未提供）

## ドキュメントとサンプル
- [x] ExecPlan ガイドライン（`docs/workflows/exec_plan_guidelines.md`）
- [x] ワークフロー追加手順（`docs/workflows/workflow_addition_guidelines.md`）
- [ ] API リファレンス / 実装ガイド（`docs/concept.md` 以外）
- [x] サンプル実装ガイドライン集約（`docs/guides/samples_guideline.md`）
- [x] `samples/in_memory_channels.py`
  - `MessageTools.fetch_messages()` を用いた既読履歴復元ログ
- [x] `samples/sqlite_channels.py`
  - `SQLChannelRepository` + `MessageTools.fetch_messages()` による再起動復元
- [x] `samples/llm_delegation.py`
  - `StandardManager.run()` 準拠（停止シグナル / ストレージ連携 / `MessageTools` 直接利用）
  - `StdIOHumanAgent` / `TextualHumanAgent` を共通ツールとして利用
  - `DelegationLLMAgent` へ LLM エージェントを統合し、`DelegationAgentTools` で依存を共有
  - Responses API `text_format` + `{"output_channel": ..., "message": ...}` の必須化
  - INFO ログと自分自身への応答禁止を追加
  - マネージャ側でチャネル参加を初期化し、`ChannelTools` 標準実装のみを使用
  - `MessageTools.fetch_messages()` で履歴スナップショットを DEBUG ログ出力
  - 設定ファイル再生成、旧 `type` 定義のクリーンアップ、`dataclass` import 修正
- [ ] 実行可能なエンドツーエンド例
- [x] ライブラリ構造図（`docs/library_structure.md`）

## レガシー資産
- [x] `legacy/src/nkaa/legacy/research_agent_v1/`・`legacy/src/nkaa/legacy/research_agent_v2/` を参照専用としてアーカイブ
- [ ] `docs/legacy/` の要点を現行ドキュメントへ移譲
