# サンプル実装ガイドライン

本ドキュメントは `samples/` 配下に新しいサンプルを追加する際の共通方針をまとめたものです。既存の InMemory チャネルデモ（`samples/in_memory_channels.py`）と同じ考え方を踏襲し、サンプル間で一貫した体験を提供します。

## 目的
- フレームワークの利用手順や API の組み合わせを最小構成で示す。
- 実運用環境に依存しない InMemory 実装をベースに、すぐに実行できる形を保つ。
- コアコンポーネント（`StandardManager`、`AgentConfig`、`ChannelTools` など）の正しい組み合わせ例を提示する。

## 基本方針
- **StandardManager を前提にする**: サンプルで扱うエージェントは `StandardManager` の設定ファイル経由でロードする。`AgentConfig` を直接継承し、ツールをエージェントとして扱わない。
- **InMemory 実装を優先**: チャネルや永続化は可能な限り InMemory 版を利用し、副作用や外部依存を避ける。必要があれば、依存先を明示し README で理由と手順を説明する。
- **逐次実行フローを明示**: `StandardManager.run()` を使わずとも理解できるよう、`apply_adapter()` 経由でエージェントに処理を委譲する手順をコードで示す。非同期制御が必要な場合は `ManagerExecutionBackend` を切り替えてスレッド実行に寄せるなど、環境制約に応じた代替手段をサンプル内で説明する。
- **生成物は `_tmp/` に隔離**: 設定ファイルやログなどの実行生成物は `_tmp/samples/<sample_name>/` 以下へ出力し、リポジトリを汚染しない。
- **テスト容易性を意識**: サンプルを pytest から再利用できる形（関数分割など）を検討し、必要ならテストモジュールから直接呼び出せる構造にする。
- **構造化出力には JSON スキーマを活用**: LLM から特定フィールドを取得したい場合は Responses API の `response_format`（JSON スキーマ指定）を用いて応答形式を固定し、予期しない回答を避ける。
- **ユーザーが即実行できる粒度で情報を返す**: サマリーだけでなく推奨アクションやリスク、確認事項などのフィールドを設計し、人間がそのまま実務に利用できる出力を目指す。

## 追加時のチェックリスト
1. `samples/README.md` にサンプルの目的・実行方法・補足事項を追記する。
2. 新規エージェント設定やツールを導入する場合、`docs/` の関連仕様（例: [docs/specs/channel_spec.md](../specs/channel_spec.md)、[docs/concept.md](../concept.md)）を更新し、影響範囲を明記する。
3. 必要に応じてテスト（`tests/samples/` など）を追加し、`make test` で検証可能な状態を保つ。
4. 環境固有の制約（例: イベントループやサンドボックスによるモジュール利用制限）がある場合は、サンプル内コメントと README の双方で理由を説明する。
5. 外部サービスや LLM API を利用する場合は、必要なパッケージ・環境変数・モデル名を README とコメントに明示する。

## 参考
- 既存の InMemory デモで利用している構成要素
  - `src/nkaa/presets/managers/single_agent_model.py`: `StandardManager` の設定スキーマ。
  - `src/nkaa/framework/channels/manager.py`: `ChannelManager` の基本操作。
  - `src/nkaa/framework/tools.py`: `ChannelTools` によるチャネル操作ヘルパ。
  - `samples/in_memory_channels.py`: ガイドラインを実際に適用したサンプル。
  - `samples/llm_delegation.py`: 役割分担と複数チャネル連携を確認できる LLM デリゲーション例。

新しいサンプルを追加する際は、本ガイドラインを満たしているかを確認し、必要であればガイドライン自体を更新してください。
