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
- [ ] エージェントが能動的にチャネル検索・購読できる API 設計（検索条件やアクセス制御など）。
  - [x] `ChannelSearchQuery`・`ChannelManager.search_channels`・`ChannelTools.search`/`join_matching` を追加し、メタデータ条件での検索と自動参加をサポート。
- [ ] メッセージペイロードのバージョニング/検証ルールと後方互換性戦略の策定。
- [ ] `ChannelManager.snapshot_unread_records()` を活用した未読スナップショット運用ポリシーとクラッシュ復旧手順の整備（暫定的に `ChannelTools.save()` で担当エージェント分を永続化）。

## Tool Injection / Adapter
- [x] アダプター経由でツールをエージェントへ渡す設計が成立 (`nkaa/framework/agent.py:120`).
- [x] 複数チャネルを束ねる `ChannelTools` の雛形を追加済み (`nkaa/framework/tools.py`).
- [ ] ツール/アダプターの高度な利用例は未整備（アクセス制御・永続化されたチャネルなどは今後の課題）。
- [ ] CLI / GUI など人間インタラクション専用のツールセットとエージェント定義は未実装（`HumanInteractionAgent` の設計とプリセット追加が必要）。

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
- [ ] 実行可能なエンドツーエンド例はまだ整っていない。
- [x] ライブラリ全体構造を説明するマーメイド図を `docs/library_structure.md` に追加。
- [x] `ChannelTools.read` を `receive` と同等の実装へ更新し、`receive` は下位互換ラッパーとして維持。

## Legacy Artifacts
- [x] `legacy/research_agent_v1/` と `legacy/research_agent_v2/` に旧試作を集約し、参照専用としてアーカイブした。
- [ ] 旧設計のドキュメントは `docs/legacy/` に移動済み。必要に応じて要点を現行ドキュメントへ移譲する。
