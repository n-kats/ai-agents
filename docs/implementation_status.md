# Implementation Checklist

## Framework Core
- [x] Base abstractions (`BaseAgent`, `BaseTools`, `BaseManager`) are defined (`nkaa/framework/agent.py`).
- [x] `AgentConfig.build` が抽象メソッド化され、サブクラス実装を強制するようになった (`nkaa/framework/agent.py:65`).
- [x] `StandardManager._load_agent` が設定ファイルを正しく読み込み、対応する `AgentConfig` サブクラスからエージェントを構築するよう修正済み (`nkaa/framework/agent.py:147`).
- [x] `StandardManager` が `ManagerExecutionBackend` 抽象を通じてプロセス / スレッド実行を切り替え可能になった（デフォルト: `multiprocessing`。`ThreadingManagerExecutionBackend` で環境制約に対応）。
- [x] `StandardManagerConfig.build_tools()` を追加し、設定から共有ツールを組み立てられるよう整備。
- [x] エージェント状態の `load/save` のデフォルト実装として `JsonLinesStateMixin` を追加し、プリセットで採用 (`nkaa/framework/persistence.py`, `nkaa/presets/managers/single_agent_model.py`).

- [x] チャンネル周りを専用パッケージへ再編し、`ChannelManager`・`ChannelTools`・キュー・リポジトリの責務を整理 (`nkaa/framework/channels/`, `nkaa/framework/tools.py`).
- [x] PostgreSQL / SQLite 向け `SQLChannelRepository` を追加し、履歴・未読テーブルと `save()` スナップショットの永続化を実装。
- [x] `ChannelTools.joined_channel_metadata()` を追加し、参加済みチャネルのメタデータを簡便に取得できる API を提供。
- [x] `StandardManager.get_agent()` を追加し、`agent_id` からエージェントを直接取得できるよう整理 (`nkaa/framework/agent.py:244`).
- [ ] エージェントが能動的にチャネル検索・購読できる API 設計（検索条件やアクセス制御など）。
  - [x] `ChannelSearchQuery`・`ChannelManager.search_channels`・`ChannelTools.search`/`join_matching` を追加し、メタデータ条件での検索と自動参加をサポート。
- [ ] メッセージペイロードのバージョニング/検証ルールと後方互換性戦略の策定。
- [ ] `MessageManager.snapshot_unread_records()` を活用した未読スナップショット運用ポリシーとクラッシュ復旧手順の整備（暫定的に `MessageTools.save()` で担当エージェント分を永続化）。
- [x] `ChannelTools` をチャネルメタデータ管理専用へ絞り、メッセージ入出力は新設した `MessageTools` に分離した。`StopMessage` 受信など終了シグナル処理も `MessageTools.read_async` で扱うように変更済み。
- [x] メッセージ配送と未読キュー管理を `MessageManager` として独立させ、`ChannelManager` はチャネルメタデータとメンバーシップ管理に専念するよう再構成した。`ChannelManager.leave_agent` からは `MessageManager` 経由で未読ポインタ破棄を呼び出す。
- [x] `MessageRouteProvider` 抽象を導入し、`MessageManager` をチャネル管理から切り離した。標準構成では `ChannelMessageRouteProvider` を用いて `ChannelManager` を適合させ、将来的なシステム向けルート追加に備える。
- [x] loguru ベースのログ基盤を整備（`configure_logging`・`LogBufferSink`・`LogStream`・`AgentLogTool`・`LogPanelAdapter`）。

## Tool Injection / Adapter
- [x] アダプター経由でツールをエージェントへ渡す設計が成立 (`nkaa/framework/agent.py:120`).
- [x] 複数チャネルを束ねる `ChannelTools` の雛形を追加済み (`nkaa/framework/tools.py`).
- [ ] ツール/アダプターの高度な利用例は未整備（アクセス制御・永続化されたチャネルなどは今後の課題）。
- [ ] CLI / GUI など人間インタラクション専用のツールセットとエージェント定義は未実装（`HumanInteractionAgent` の設計とプリセット追加が必要）。
  - [x] Textual ベースの人間エージェントを追加し、対話 UI を拡張可能なプリセットを用意 (`nkaa/presets/agents/textual_human.py`).
  - [x] TextualHumanAgent がメインスレッド以外で実行されてもシグナル登録エラーで停止しないよう改善。
  - [x] TextualHumanAgent に LogPanelAdapter を組み込み、タブ切り替えでチャット／ログを表示し、レベル・エージェント・チャネルで絞り込めるよう整備。
  - [x] TextualHumanAgent が UI 終了後に stop_manager ツールを発火するよう調整し、終了時に画面が崩れないようにした。
  - [x] TextualHumanAgent のチャット／ログパネルで RichLog を優先使用し、長文でも自動的に折り返すよう改善。
- [x] LLM 呼び出しを非同期化し、停止イベント受信時に進行中リクエストをキャンセルできる構成を整備する。
  - [x] `ChannelManager` / `ChannelTools` を `asyncio` 対応へ拡張し、非同期ポーリングおよび書き込みを安全に扱えるようにする。
  - [x] `StandardManager` に `run_async()` を追加し、イベントループ主導でエージェント実行キューと停止シグナルを管理する（`run()` 互換は任意の薄いラッパーとする）。
  - [x] `DelegationLLMAgent` を含むエージェントに `run_async()` を実装し、チャネル読み取り・LLM 呼び出し・結果送信を `await` で繋ぎ、停止要求時はタスクキャンセル → 状態保存 → ループ停止を明示的に制御する。
  - [x] `LLMCallTool` にキャンセル可能なリクエスト実装（タイムアウト設定やキャンセル用ハンドラ）を追加する。
  - [x] 非同期化に伴うログ・履歴・チャネル永続化の排他制御（`asyncio.Lock` 等）の指針をまとめ、ドキュメントへ反映する。
  - [x] `shutdown_grace_period` を導入し、キャンセルに応答しない LLM 呼び出しでも終了処理がブロックされないようグレースタイムアウトを追加した。
  - [x] 擬似 LLM での停止回避ケースを再現するテスト (`tests/samples/test_llm_delegation_shutdown.py`) を追加した。
  - [x] チャネル経路とは独立した停止シグナル `StopMessage` を導入し、`ChannelTools.read_async` で協調停止を通知できるようにした。
  - [ ] 詳細計画は `docs/features/async_llm_shutdown.md` を参照。

## Presets
- [x] シングルエージェント向けプリセットとツール束ねの例が存在 (`nkaa/presets/managers/single_agent_model.py`).
- [x] `SimpleAgentConfig.build` が自身を渡して `SingleAgent` を構築するよう修正済み (`nkaa/presets/managers/single_agent_model.py:64`).
- [x] `LLMCallTool` を gpt-5 系 Responses API 対応の本実装へ置き換え (`nkaa/presets/tools/llm_tool.py`).
- [ ] `InputTool` がダミー実装のままで、実運用向けツールは未提供。

## Documentation / Examples
- [ ] ドキュメントはコンセプト草案のみで、API リファレンスや実装ガイドは未整備 (`docs/concept.md`).
- [x] サンプル実装ガイドラインを整備し、`docs/samples_guideline.md` に方針を集約。
- [x] LLM 協調サンプルを `samples/llm_delegation.py` として追加し、複数チャネル活用例を提示。
  - [x] `StandardManager.run()` パターンへ移行し、スレッド実行・停止シグナル・ストレージ連携を整理。
  - [x] 人間エージェントをプリセットの `StdIOHumanAgent` へ統合し、サンプルでのツール再利用を一本化。
  - [x] Textual ベース UI の `TextualHumanAgent` をサンプルで利用し、入力中でも他チャネルからの更新を確認できるようにした。
  - [x] カスタムツールクラスを廃止し、`ChannelTools` を直接所有する構成で停止シグナルをエージェントへ伝播。
  - [x] 2 つの LLM エージェントを `DelegationLLMAgent` に統合し、プロンプト差分のみで役割を切り替えられるよう簡素化。
  - [x] LLM ツールは `DelegationAgentTools` で共有し、`attach_*` に頼らずアダプター経由で依存を渡す構成へ修正。
  - [x] Responses API の `text_format` を活用し、Pydantic モデル経由で構造化レスポンスを取得するよう更新。
  - [x] サンプル実行時に生成済み JSON 設定を再作成し、旧バージョンの `type` 定義が残らないようクリーンアップを追加。
  - [x] フローを「人間 ↔ 受付 ↔ 思考担当」へ整理し、思考結果を受付経由で人間へ返すようチャネル経路を再構築。
  - [x] LLM 呼び出し前後に INFO ログを出力し、実行状況を追跡できるようにした。
  - [x] チャンネル参加はマネージャー側で初期化し、エージェントは `ChannelTools.receive` を通じた受信に専念する構成へ変更。
  - [x] LLM への依頼は `{"output_channel": ..., "message": ...}` の構造化レスポンスを必須とし、自分自身の投稿へ応答しない安全策を追加。
  - [x] サンプル全体を約半分の行数へ整理し、役割切替ロジックと設定を単純化。
  - [x] チャネル説明のみを用いて出力先を選択できるようエージェント／チャンネルの role 分岐を廃止し、プロンプト制御へ一本化。
  - [x] Delegation サンプルで `ChannelTools` の標準実装を直接利用するよう整理し、参加済みチャネルだけを扱うロジックを共有化。
  - [x] `samples/llm_delegation.py` で発生していた `dataclass` 未 import による実行時エラーを修正。
- [ ] 実行可能なエンドツーエンド例はまだ整っていない。
- [x] ライブラリ全体構造を説明するマーメイド図を `docs/library_structure.md` に追加。
- [x] `ChannelTools.read` を `receive` と同等の実装へ更新し、チャネルID引数を廃止して内部で参加チャネルのみを返すよう統一。

## Legacy Artifacts
- [x] `legacy/research_agent_v1/` と `legacy/research_agent_v2/` に旧試作を集約し、参照専用としてアーカイブした。
- [ ] 旧設計のドキュメントは `docs/legacy/` に移動済み。必要に応じて要点を現行ドキュメントへ移譲する。
