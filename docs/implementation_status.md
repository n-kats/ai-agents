# Implementation Checklist

## Framework Core
- [x] Base abstractions (`BaseAgent`, `BaseTools`, `BaseManager`) are defined (`nkaa/framework/agent.py`).
- [x] `AgentConfig.build` が抽象メソッド化され、サブクラス実装を強制するようになった (`nkaa/framework/agent.py:65`).
- [x] `StandardManager._load_agent` が設定ファイルを正しく読み込み、対応する `AgentConfig` サブクラスからエージェントを構築するよう修正済み (`nkaa/framework/agent.py:147`).
- [ ] エージェント状態の `load/save` のデフォルト実装は無く、サンプルも未提供。

## Channel / Messaging
- [x] メッセージ型と優先度付きキューのスケルトンは用意済み (`nkaa/framework/messages.py`, `nkaa/framework/channel.py`).
- [x] `ChannelManager` がインメモリチャネル登録・生成・保存フックを持つように整理され、基本的な操作が利用可能 (`nkaa/framework/channel.py:55`).
- [x] `MessageQueue.put/get` の不整合修正と `Empty` ハンドリング追加により、未定義引数や空キュー時の例外を回避 (`nkaa/framework/channel.py:126`).

## Tool Injection / Adapter
- [x] アダプター経由でツールをエージェントへ渡す設計が成立 (`nkaa/framework/agent.py:120`).
- [x] 複数チャネルを束ねる `ChannelTools` の雛形を追加済み (`nkaa/framework/tools.py`).
- [ ] ツール/アダプターの高度な利用例は未整備（アクセス制御・永続化されたチャネルなどは今後の課題）。

## Presets
- [x] シングルエージェント向けプリセットとツール束ねの例が存在 (`nkaa/presets/managers/single_agent_model.py`).
- [x] `SimpleAgentConfig.build` が自身を渡して `SingleAgent` を構築するよう修正済み (`nkaa/presets/managers/single_agent_model.py:64`).
- [ ] `LLMCallTool` や `InputTool` がダミー実装のままで、実運用向けツールは未提供 (`nkaa/presets/tools/llm_tool.py`).

## Documentation / Examples
- [ ] ドキュメントはコンセプト草案のみで、API リファレンスや実装ガイドは未整備 (`docs/concept.md`).
- [ ] 実行可能なエンドツーエンド例はまだ整っていない。

## Legacy Artifacts
- [ ] `research_agent_v1/v2` は旧試作で設計方針と乖離。整理 (削除/アーカイブ) 方針が未決定。
