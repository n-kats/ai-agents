# Agent Development Notes

## Concept
- 基本思想やコンセプトは `docs/concept.md` を参照してください。軽量なマルチエージェント基盤を提供し、プロセス制御や状態管理をフレームワーク側に寄せる設計方針をまとめています。

## コア構造
- エージェント／ツール／マネージャの抽象は `nkaa/framework/agent.py:11` 以降で定義されており、`StandardManager` が複数プロセス実行と停止ハンドリングを担当します。
- チャンネルとメッセージの骨組みは `nkaa/framework/channel.py:18` と `nkaa/framework/messages.py:2` にあります。複数チャンネルを束ねる想定と read/write API の雛形があるものの、実装は未完成です。
- プリセット例は `nkaa/presets/managers/single_agent_model.py:55` にあり、`BaseTools` による依存注入やアダプター利用 (`nkaa/presets/managers/single_agent_model.py:155`) の最小パターンが確認できます。

## アダプター利用の意図
- ツールの受け渡しをカスタマイズするフックとしてアダプターを使用します。設計の背景と利点は `docs/concept.md` の「アダプターの役割と利点」を参照してください。

## 実装状況と課題
- 進捗チェックリストは `docs/implementation_status.md` にまとめています。未実装箇所や既知の不具合（例: `AgentConfig.build` 未実装、`ChannelManager` スタブなど）を確認できます。

## 作業ガイドライン
1. 新しいエージェントを追加する際は、`AgentConfig.build` 周りの不足を解消しつつ、`StandardManager` とアダプター経由でツールを注入する流れを踏襲してください。
2. チャンネル機能を拡張する場合は、read/write API と優先度付きキューの既存骨組みを活かしつつ、`ChannelManager` の永続化・検索ロジックを実装してください。
3. 実運用を見据えたツール（LLM クライアント、入力処理、ログ周りなど）は `nkaa/presets/tools/` のダミー実装を置き換える形で追加してください。

## 関連メモ
- 旧実装 (`nkaa/research_agent_v1` / `nkaa/research_agent_v2`) は設計検討用の履歴であり、現行方針の直接参照は不要です。整理方針は `docs/implementation_status.md` の「Legacy Artifacts」を参照してください。
