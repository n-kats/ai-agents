# 実装進捗チェックリスト

## フレームワーク基盤
- [x] 基底抽象（`BaseAgent`・`BaseTools`・`BaseManager`）を定義済み（`nkaa/framework/agent.py`）。
- [x] `AgentConfig.build()` を抽象メソッド化し、サブクラスに実装を必須化。
- [x] `StandardManager._load_agent()` が設定ファイルから `AgentConfig` 派生クラスを読み込み、対応エージェントを生成するよう調整。
- [x] `StandardManager` が `ManagerExecutionBackend` を介してプロセス / スレッド実行を切り替え可能（デフォルトは `multiprocessing`、制約環境では `ThreadingManagerExecutionBackend` を使用）。
- [x] `StandardManagerConfig.build_tools()` を追加し、設定から共有ツールを構築できるようにした。
- [x] エージェント状態の標準実装として `JsonLinesStateMixin` を追加し、プリセットから利用（`nkaa/framework/persistence.py`、`nkaa/presets/managers/single_agent_model.py`）。
- [x] チャネル関連を専用パッケージへ再編し、`ChannelManager`・`ChannelTools`・キュー・リポジトリの責務を分離（`nkaa/framework/channels/`、`nkaa/framework/tools.py`）。
- [x] PostgreSQL / SQLite 向けの `SQLChannelRepository` を追加し、履歴・未読テーブルおよび `save()` スナップショット永続化を実装。
- [x] `ChannelTools.joined_channel_metadata()` を追加し、参加済みチャネルのメタデータを取得しやすくした。
- [x] `StandardManager.get_agent()` を追加し、`agent_id` からエージェントを直接取得できるよう整理。
- [ ] エージェントが能動的にチャネル検索・購読できる API 設計（検索条件やアクセス制御の整理）。
  - [x] `ChannelSearchQuery`・`ChannelManager.search_channels`・`ChannelTools.search` / `join_matching` を追加し、メタデータ条件での検索と自動参加をサポート。
- [ ] メッセージペイロードのバージョニング / 検証ルールと後方互換性戦略の策定。
- [ ] `MessageManager.snapshot_unread_records()` を活用した未読スナップショット運用ポリシーとクラッシュ復旧手順の整備（暫定的に `MessageTools.save()` が担当エージェント分を永続化）。
- [x] `ChannelTools` をチャネルメタデータ管理専用に絞り、メッセージ入出力は `MessageTools` に分離。`StopMessage` 受信など終了シグナル処理も `MessageTools.read_async()` で対応。
- [x] メッセージ配送と未読キュー管理を `MessageManager` として独立させ、`ChannelManager` はチャネルメタデータとメンバーシップ管理に専念（`ChannelManager.leave_agent()` から `MessageManager` 経由で未読ポインタを破棄）。
- [x] `MessageRouteProvider` 抽象を導入し、`MessageManager` をチャネル管理から切り離してルーティングを差し替え可能にした（標準構成は `ChannelMessageRouteProvider`）。
- [x] loguru ベースのログ基盤を整備し、`configure_logging`・`LogBufferSink`・`LogStream`・`AgentLogTool`・`LogPanelAdapter` を提供。
- [x] メッセージ未読キューのデータベース常時永続化とバックエンド切り替えを実装（[docs/plans/exec_plan_message_database.md](./plans/exec_plan_message_database.md) 参照）。
  - [x] `channel_unread` に `(agent_id, priority, enqueued_at, id)` の複合インデックスを追加し、`allowed_channels` フィルタの回帰テストを整備。
  - [x] `MessageTools.fetch_message(s)` を追加し、既読後の履歴をチャネル ID / メッセージ ID から再取得できるようにした。
- [x] `MessageManager.list_channel_messages()` / `MessageTools.list_channel_messages()` を実装し、チャネル全体の履歴確認やレポート生成を簡易化。
- [ ] Opik 連携のクラウド版対応および Langfuse 連携手段の検討（優先度: 低）

## ツール注入とアダプター
- [x] アダプター経由でツールをエージェントへ渡す設計を確立（`nkaa/framework/agent.py`）。
- [x] 複数チャネルを束ねる `ChannelTools` の雛形を整備（`nkaa/framework/tools.py`）。
- [x] `LLMCallTool` の対話型検証サンプルを追加し、標準入力で指示を受けて OpenAI Responses API を呼び出せるようにした（`samples/llm_call_tool_interactive.py`）。
- [ ] ツール / アダプターの高度な利用例（アクセス制御・永続化チャネル連携など）は未整備。
- [ ] CLI / GUI など人間インタラクション専用のツールセットとエージェント定義は未実装（`HumanInteractionAgent` の設計とプリセット追加が必要）。
  - [x] Textual ベースの人間エージェントを追加し、拡張可能な対話 UI プリセットを提供（`nkaa/presets/agents/textual_human.py`）。
  - [x] TextualHumanAgent がメインスレッド以外で実行されてもシグナル登録エラーで停止しないよう改善。
  - [x] TextualHumanAgent に `LogPanelAdapter` を組み込み、チャット / ログのタブ切り替えとレベル・エージェント・チャネルでの絞り込みを可能にした。
  - [x] TextualHumanAgent が UI 終了後に `stop_manager` ツールを発火し、終了時に画面が崩れないよう調整。
  - [x] TextualHumanAgent のチャット / ログパネルで `RichLog` を優先使用し、長文を自動で折り返すよう改善。
- [x] LLM 呼び出しを非同期化し、停止イベント受信時に進行中リクエストをキャンセルできる構成を整備。
  - [x] `ChannelManager` / `MessageTools` を `asyncio` 対応へ拡張し、非同期ポーリングと書き込みを安全に扱えるようにした。
  - [x] `StandardManager` に `run_async()` を追加し、イベントループ主導でエージェント実行キューと停止シグナルを管理（`run()` は互換ラッパー）。
  - [x] `DelegationLLMAgent` などに `run_async()` を実装し、受信・LLM 呼び出し・送信を `await` で連結。停止要求時はタスクキャンセル → 状態保存 → ループ停止を明示的に制御。
  - [x] `LLMCallTool` にキャンセル可能なリクエスト実装（タイムアウト設定やキャンセルハンドラ）を追加。
  - [x] 非同期化に伴うログ / 履歴 / チャネル永続化の排他制御（`asyncio.Lock` など）の指針を整理し、ドキュメントへ反映。
  - [x] `shutdown_grace_period` を撤廃し、停止時は即時キャンセルのみを行う構成へ整理（LLM タイムアウト仕様を削除）。
  - [x] 擬似 LLM で停止回避ケースを再現するテスト（`tests/samples/test_llm_delegation_shutdown.py`）を追加。
  - [x] チャネル経路とは独立した停止シグナル `StopMessage` を導入し、`MessageTools.read_async()` で協調停止を通知できるようにした。
  - [ ] 詳細計画は [docs/plans/async_llm_shutdown.md](./plans/async_llm_shutdown.md) を参照（継続タスク）。

## プリセット
- [x] シングルエージェント向けプリセットとツール束ねの例を追加（`nkaa/presets/managers/single_agent_model.py`）。
- [x] `SimpleAgentConfig.build()` が自身を渡して `SingleAgent` を構築するよう修正。
- [x] `LLMCallTool` を GPT-5 系 Responses API 対応の実装へ移行（`nkaa/presets/tools/llm_tool.py`）。
- [ ] `InputTool` はダミー実装のままで、実運用向けツールは未提供。

## ドキュメントとサンプル
- [x] ExecPlan ガイドラインを [docs/workflows/exec_plan_guidelines.md](./workflows/exec_plan_guidelines.md) に整備。
- [x] ワークフロー追加手順を [docs/workflows/workflow_addition_guidelines.md](./workflows/workflow_addition_guidelines.md) に整備。
- [ ] ドキュメントはコンセプト草案のみで、API リファレンスや実装ガイドは未整備（[docs/concept.md](./concept.md)）。
- [x] サンプル実装ガイドラインを [docs/guides/samples_guideline.md](./guides/samples_guideline.md) に集約。
- [x] InMemory チャネルデモ（`samples/in_memory_channels.py`）に `MessageTools.fetch_messages()` を組み込み、既読メッセージの履歴復元手順をログで確認可能にした。
- [x] SQLite チャネル永続化サンプル（`samples/sqlite_channels.py`）を追加し、`SQLChannelRepository` と `MessageTools.fetch_messages()` による再起動復元フローを実行可能にした。
- [x] LLM 協調サンプルを `samples/llm_delegation.py` として追加し、複数チャネルを活用する例を提示。
  - [x] `StandardManager.run()` パターンへ移行し、スレッド実行・停止シグナル・ストレージ連携を整理。
  - [x] 人間エージェントをプリセットの `StdIOHumanAgent` へ統合し、サンプルでのツール再利用を一本化。
  - [x] Textual ベース UI の `TextualHumanAgent` をサンプルで利用し、入力中でも他チャネルの更新を確認できるようにした。
  - [x] カスタムツールクラスを廃止し、`MessageTools` を直接使う構成で停止シグナルをエージェントへ伝播。
  - [x] 2 つの LLM エージェントを `DelegationLLMAgent` に統合し、プロンプト差分のみで役割を切り替えられるよう簡素化。
  - [x] LLM ツールは `DelegationAgentTools` で共有し、`attach_*` に頼らずアダプター経由で依存を渡す構成へ修正。
  - [x] Responses API の `text_format` を活用し、Pydantic モデル経由で構造化レスポンスを取得するよう更新。
  - [x] サンプル実行時に生成済み JSON 設定を再作成し、旧バージョンの `type` 定義が残らないようクリーンアップを追加。
  - [x] フローを「人間 ⇄ 受付 ⇄ 思考担当」へ整理し、思考結果を受付経由で人間へ返すチャネル構成を再設計。
  - [x] LLM 呼び出し前後に INFO ログを出力し、実行状況を追跡できるようにした。
  - [x] チャンネル参加はマネージャー側で初期化し、エージェントは `MessageTools` 経由の受信処理に専念する構成へ変更。
  - [x] LLM への依頼は `{"output_channel": ..., "message": ...}` の構造化レスポンスを必須とし、自分自身の投稿へ応答しない安全策を追加。
  - [x] サンプル全体の行数を半減させ、役割切替ロジックと設定を単純化。
  - [x] チャネル説明だけで出力先を選択できるようにし、エージェント / チャネルの role 分岐を廃止してプロンプト制御へ統一。
  - [x] 受付・分析プロンプトの文章を役割／判断基準中心に再設計し、JSON 構造を意識せず自然文レポートを生成させる方針へ更新。
  - [x] Delegation サンプルで `ChannelTools` の標準実装を直接利用し、参加済みチャネルのみを扱うロジックを共有化。
  - [x] `samples/llm_delegation.py` で発生していた `dataclass` 未 import による実行時エラーを修正。
  - [x] 受信済みメッセージの `(channel_id, message_id)` を保持し、`MessageTools.fetch_messages()` で履歴スナップショットを DEBUG ログに出力する処理を追加。
- [ ] 実行可能なエンドツーエンド例はまだ整っていない。
- [x] ライブラリ全体構造を説明するマーメイド図を [docs/library_structure.md](./library_structure.md) に追加。

## レガシー資産
- [x] `legacy/research_agent_v1/` と `legacy/research_agent_v2/` に旧試作を集約し、参照専用としてアーカイブした。
- [ ] 旧設計のドキュメントは `docs/legacy/` に移動済み。必要に応じて要点を現行ドキュメントへ移譲するタスクが残っている。
