# Samples

`samples/` にはフレームワークの主要機能を最小構成で体験できるスクリプトを配置します。追加・更新時は `docs/samples_guideline.md` の方針に従って構成とドキュメントを整備してください。

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
3. 別の `AlertPublisher` が複数メッセージを送信し、`AlertSubscriber` が未読を処理。
4. 追加のアラート送信後、`SnapshotObserver` が `ChannelManager.snapshot_unread_records()` を通じて未読スナップショットを採取・永続化し、新しい `ChannelManager` を復元して未読が保持されていることを確認します。

> メモ: サンプル実行時は `ThreadingManagerExecutionBackend` を指定して `StandardManager` をスレッド実行モードに切り替えています。`StandardManager.run()` は呼び出さず、`apply_adapter` を通じてエージェントを逐次実行する構成です。

## LLM デリゲーション協調デモ
- ファイル: `samples/llm_delegation.py`
- 内容: 人間役エージェントが依頼を投入し、フロント担当 (`FrontDeskAgent`) が分析担当 (`AnalystAgent`) と連携して要約・結論を返すマルチエージェントフロー。`human_support` と `analysis_workspace` の 2 チャネルを使い分け、役割分担とメッセージ転送を確認します。
- 実行方法:
  ```bash
  python samples/llm_delegation.py
  ```
  実行時に `_tmp/samples/llm_delegation/` 配下へエージェント設定が生成されます。
- 依頼入力: スクリプト開始後、まず `StdIOHumanAgent` が利用するチャネルを選択するプロンプトが表示されます。続いて依頼文を入力（空行で終了）すると対話が開始され、以降はチャネル名と共に受信メッセージが表示されるたびに返信内容の入力が促されます。
- 前提環境: `pip install openai` を実施し、`OPENAI_API_KEY` に OpenAI の API キーを設定してください。
- 使用モデル: フロント担当が `gpt-5-nano`、分析担当が `gpt-5-mini` を呼び出して要約・結論を生成します。
- 流れ:
  1. `FrontDeskAgent` と `AnalystAgent` がそれぞれ担当チャネルへ参加し、待機状態を整えます。
  2. `StdIOHumanAgent` が実行時に利用可能なチャネル一覧を取得し、ユーザーが選択したチャネル（例: `human_support`）へ依頼を投稿。
  3. `FrontDeskAgent` が依頼を受信して `analysis_workspace` へ転送。
  4. `AnalystAgent` が依頼内容を解析し、結論・要約を `analysis_workspace` に返信。
  5. `FrontDeskAgent` が要約を `human_support` へ送り返し、`StdIOHumanAgent` がチャネル名付きで内容を表示し、必要に応じて追加入力を促します。
- 応答内容: `AnalystAgent` は JSON スキーマに従ってサマリー・結論・推奨アクション・リスク・確認事項を生成し、`StdIOHumanAgent` はチャネル名・メッセージ内容を整形表示したうえで標準入力からの応答を受け付けます。

> メモ: LLM 呼び出しでは OpenAI Responses API の `response_format` を JSON スキーマ指定で利用し、アウトラインとサマリーの構造化を強制しています。実行前に `OPENAI_API_KEY` を設定し、各モデルが利用可能なアカウントを用意してください。
