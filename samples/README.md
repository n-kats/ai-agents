# Samples

`samples/` にはフレームワークの主要機能を最小構成で体験できるスクリプトを配置します。追加・更新時は `docs/guides/samples_guideline.md` の方針に従って構成とドキュメントを整備してください。

## InMemory チャネルデモ（StandardManager 使用）
- ファイル: `samples/in_memory_channels.py`
- 内容: `StandardManager` が JSON 設定からデモエージェントをロードし、`ChannelTools` を介してチャネル生成・検索・未読管理を行う流れを確認できます。
- 実行方法:
  ```bash
  python samples/in_memory_channels.py
  ```
  実行時に `_tmp/samples/standard_manager/` 配下へ設定ファイルが生成されます。

### 動作概要
1. `AlertPublisher`（bootstrap 用）がチャネルを生成し、`ChannelMetadata` を出力。
2. `AlertSubscriber` が `ChannelSearchQuery` を使ってチャネルへ参加し、以降のメッセージを受信。
3. 別の `AlertPublisher` が複数メッセージを送信し、`AlertSubscriber` が未読を処理しながら `(channel_id, message_id)` の組を保存。
4. 受信済みメッセージを `MessageTools.fetch_messages()` で再取得し、再起動後の履歴復元方法をログに出力。
5. 追加のアラート送信後、`SnapshotObserver` が `MessageManager.snapshot_unread_records()` を通じて未読スナップショットを採取・永続化し、新しい `ChannelManager` / `MessageManager` を復元して未読が保持されていることを確認します。

> メモ: サンプル実行時は `ThreadingManagerExecutionBackend` を指定して `StandardManager` をスレッド実行モードに切り替えています。`StandardManager.run()` は呼び出さず、`apply_adapter` を通じてエージェントを逐次実行する構成です。

## SQLite チャネル永続化デモ
- ファイル: `samples/sqlite_channels.py`
- 内容: `SQLChannelRepository` を用いて `channel_messages` / `channel_unread` を SQLite ファイルへ永続化し、再起動後に `MessageTools.fetch_messages()` で既読履歴を復元する流れを確認できます。
- 実行方法:
  ```bash
  python samples/sqlite_channels.py
  ```
  `_tmp/samples/sqlite_channels/` に `channels.sqlite`（DB ファイル）と `subscriber_history.json`（受信済みメッセージ ID）が生成されます。

### 動作概要
1. `AlertPublisher`（bootstrap）がチャネルを作成（投稿なし）。
2. `LimitedSubscriber` がメタデータ検索でチャネルに参加し、最大 2 件までメッセージを受信して `(channel_id, message_id)` を保存。
3. `AlertPublisher`（main/followup）が一定時間待機後にメッセージを投稿し、受信したメッセージは SQLite 上の `channel_messages` に永続化される。
4. `PersistenceReporter` が `MessageManager.snapshot_unread_records()` の結果を記録し、マネージャー停止を要求。
5. サンプル末尾で `SQLChannelRepository` を再接続し、`subscriber_history.json` のポインタを使って `MessageTools.fetch_messages()` を実行。履歴内容が DEBUG/INFO ログに表示されます。

> メモ: SQLite は同一プロセス内で共有するため `check_same_thread=False` を指定しています。PostgreSQL へ切り替える際は `db_url` を変更し、必要なドライバ（例: `psycopg[binary]`）をインストールしてください。

## LLM デリゲーション協調デモ
- ファイル: `samples/llm_delegation.py`
- 内容: Textual ベースの人間役エージェントが相談を投稿し、受付エージェントが分析エージェントへ依頼をルーティングして結果を返すマルチエージェントフロー。`human_support` と `analysis_workspace` の 2 チャネルを使い分け、役割分担とメッセージ転送を確認します。
- 実行方法:
  ```bash
  python samples/llm_delegation.py
  ```
  実行時に `_tmp/samples/llm_delegation/` 配下へエージェント設定が生成されます。
- 依頼入力: 起動すると Textual ベースの人間用 UI が開き、左ペインで送信先チャネル、中央でメッセージログ、右タブでログビューを確認できます。入力欄へ依頼文を入力（Enter で送信）すると対話が開始され、`終了` ボタンまたは `/quit` コマンドでマネージャ停止を要求できます。
- 前提環境: `pip install openai` を実施し、`OPENAI_API_KEY` に OpenAI の API キーを設定してください。
- 使用モデル: 受付・分析の両エージェントが `gpt-5-mini` を呼び出して応答を生成します。
- 流れ:
  1. `TextualHumanAgent`（人間役）が UI で依頼文を `human_support` へ投稿。
  2. 受付エージェントが相談内容を要約し、分析の観点や確認事項・推奨アクションを整理した依頼文を `analysis_workspace` に送る。
  3. 分析エージェントが依頼を解析し、洞察・推奨策・追加で確認したい点などを含むレポートを生成して `human_support` へ返す。
  4. 受付エージェントが分析結果を読みやすい文章に整え直し、`human_support` へ届ける。
  6. 各 LLM エージェントは受信済みメッセージの `(channel_id, message_id)` を保持し、`MessageTools.fetch_messages()` で直近履歴を再取得して DEBUG ログへ出力します。
  7. 終了時に `MessageTools.list_channel_messages()` とログリングバッファを用いたサマリーを標準出力へ整形表示し、チャネル履歴とエージェント別ログをそのまま確認できます。
- 応答内容: 受付・分析それぞれの LLM プロンプトが自然言語でのレポート生成手順を指示しており、`message.content` には人間がそのまま読める文章（要約・洞察・推奨アクションなど）が挿入されます。`TextualHumanAgent` はチャネル名とメッセージ内容を整形表示し、ユーザーに追加入力を促します。
  - 受付エージェント: `要約 / 背景・制約 / 分析で深掘りすべき観点 / 推奨アクション`
  - 分析エージェント: `状況整理 / 分析結果 / 推奨アクション / リスク・懸念 / 追加で確認したい事項`

> メモ: LLM 呼び出しでは OpenAI Responses API と Pydantic モデルを組み合わせて構造化レスポンスをパースします。実行前に `OPENAI_API_KEY` を設定し、各モデルが利用可能なアカウントを用意してください。

## LLMCallTool 対話デモ
- ファイル: `samples/llm_call_tool_interactive.py`
- 内容: `LLMCallTool` を利用して OpenAI Responses API を呼び出し、標準入力で受け取った指示文に対する構造化レスポンスを取得するサンプル。
- 実行方法:
  ```bash
  export OPENAI_API_KEY=...  # OpenAI の API キー
  python samples/llm_call_tool_interactive.py
  ```
- 動作概要:
  1. `LLMCallTool` が環境変数 `OPENAI_API_KEY` から API キーを読み込み、OpenAI Responses API へ接続します。
  2. `call_parsed()` を利用して `GuidanceResponse` モデルに適合した構造化レスポンスを取得します。
  3. 取得した JSON データを標準出力へ整形表示し、実際に LLM を呼び出せているか確認できます（ネットワーク接続と OpenAI アカウントが必要です）。
