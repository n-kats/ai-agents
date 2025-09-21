# Implementation Checklist

## Framework Core
- [x] Base abstractions (`BaseAgent`, `BaseTools`, `BaseManager`) are defined (`nkaa/framework/agent.py`).
- [ ] `AgentConfig.build` 実装が未着手で、具体的なエージェント構築ができない (`nkaa/framework/agent.py:61`).
- [ ] `StandardManager._load_agent` が設定ファイルを正しく読み込むロジックになっていない（Path を `json.loads` へ渡している） (`nkaa/framework/agent.py:144`).
- [ ] エージェント状態の `load/save` のデフォルト実装は無く、サンプルも未提供。

## Channel / Messaging
- [x] メッセージ型と優先度付きキューのスケルトンは用意済み (`nkaa/framework/messages.py`, `nkaa/framework/channel.py`).
- [ ] チャンネル検索・永続化など `ChannelManager` の中身が全て未実装 (`nkaa/framework/channel.py:18`).
- [ ] `MessageQueue.put` が未定義の `timestamp` 引数を `OrderedMessage` に渡しており、動作未確認 (`nkaa/framework/channel.py:62`).

## Tool Injection / Adapter
- [x] アダプター経由でツールをエージェントへ渡す設計が成立 (`nkaa/framework/agent.py:120`).
- [ ] ツール/アダプターの高度な利用例は未整備（アクセス制御・複数チャネル束ねなどは設計のみ）。

## Presets
- [x] シングルエージェント向けプリセットとツール束ねの例が存在 (`nkaa/presets/managers/single_agent_model.py`).
- [ ] `SingleAgent` のコンストラクタが `SimpleAgentConfig` を受け取るよう配線されていない（`build` が引数なしで `SingleAgent()` を生成） (`nkaa/presets/managers/single_agent_model.py:63`).
- [ ] `LLMCallTool` や `InputTool` がダミー実装のままで、実運用向けツールは未提供 (`nkaa/presets/tools/llm_tool.py`).

## Documentation / Examples
- [ ] ドキュメントはコンセプト草案のみで、API リファレンスや実装ガイドは未整備 (`docs/concept.md`).
- [ ] 実行可能なエンドツーエンド例はまだ整っていない。

## Legacy Artifacts
- [ ] `research_agent_v1/v2` は旧試作で設計方針と乖離。整理 (削除/アーカイブ) 方針が未決定。
