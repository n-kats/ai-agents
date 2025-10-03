# ログ基盤仕様（loguru ベース）

本書はフレームワーク全体で共有するログ基盤の設計方針をまとめる。loguru を中心に、Textual CUI との連携やエージェント向けツール提供を前提とした構成とする。

## 目的

- `logger.info(...)` など loguru 標準 API をそのまま利用できる開発体験を維持する。
- Textual ベースの CUI を含む複数の閲覧手段（標準出力・ファイル・JSON・リングバッファ）へ同時出力する。
- エージェント固有のメタデータ（`agent_id`、`channel`、`task_id` など）を統一的に付与・フィルタリングできる。
- 設定ファイルを用意せず、シンプルな初期化関数でオン／オフや出力パスを指定できる。

## 初期化 API

```python
from nkaa.logging import configure_logging

configure_logging(
    enable_console: bool = False,
    log_file: str | Path | None = None,
    json_file: str | Path | None = None,
    buffer_limit: int = 500,
)
```

- `enable_console` : `True` の場合は標準出力へ INFO 以上を出力するコンソールシンクを追加。
- `log_file` : 指定時にローテーション付きテキストファイルシンクを登録。`None` の場合は追加しない。
- `json_file` : 指定時に NDJSON 形式のシンクを登録。解析系の取り込みを想定。
- `buffer_limit` : Textual / CUI 向けリングバッファ（`LogBufferSink`）が保持する最大件数。

呼び出し後は loguru のグローバルロガーに対して複数シンクが登録された状態になり、アプリケーション側は `logger.debug(...)` など通常の呼び方を行うだけで良い。

### 状態取得ヘルパー

`get_logging_state()` を公開し、現在の構成を参照できるようにする。戻り値には以下を含める。

- シンク一覧（名前、種別、出力先パス、設定レベル、バッファ件数など）
- Textual/CUI バッファの現在サイズとフィルタ条件
- グローバルレベルや環境変数による上書き状況

この情報を用いて「INFO レベルは出力されるか」「JSON シンクは有効か」といった確認が可能になる。

## LogBufferSink と LogStream

- `LogBufferSink` は loguru シンクとして登録され、構造化ログ (`timestamp`, `level`, `message`, `context`) をリングバッファに保持する。
- `LogBufferSink.get_stream()` で購読用の `LogStream` を取得できる。`LogStream` は以下のメソッドを持つ:
  - `snapshot(limit: int | None = None) -> list[LogRecord]`
  - `subscribe(callback: Callable[[LogRecordEvent], None]) -> Subscription`
  - `set_filters(level: str | None = None, **context_filters) -> None`
- フィルタは `agent_id`, `channel`, `task_id` などコンテキストキーで指定する。未指定の場合は全件を対象とする。

## LogPanelAdapter（Textual 連携）

- Textual UI へログを表示するための仲介クラス。`LogStream` を購読し、指定ウィジェット（標準では `RichLog`）へ追記する。
- 主な API:
  - `adapter = LogPanelAdapter(log_stream, widget_factory=RichLog, level="INFO")`
  - `widget = adapter.install(app)` : Textual アプリの `compose()` などで呼び出し、配置用ウィジェットを取得。
  - `adapter.start()` / `adapter.stop()` : `on_mount` / `on_unmount` で購読開始・終了。
  - `adapter.set_level("WARNING")` や `adapter.set_filters(agent_id="planner")` で表示対象をランタイム制御。
- `push(record)` は購読コールバックから呼ばれ、Textual のスレッド安全性を考慮して `app.call_from_thread` 経由でウィジェットを更新する。
- スナップショット表示（初期描画・再読込）と追随表示の両方に対応し、CUI 上でのログ監視を簡潔に実装できる。

## AgentLogTool（エージェントへの注入）

- `StandardManagerConfig.build_tools()` で生成されるツールセットに含める。各エージェントには `AgentLogTool` が渡され、以下の API を提供する。
  - `tools.log.logger` : `logger.bind(agent_id=...)` 済みの loguru ロガー。`logger.info(...)` など直接利用できる。
- `tools.log.context(**metadata)` : `contextmanager`。ブロック内のログへ追加メタデータを付与。
- `tools.log.get_stream()` : 当該エージェントにフィルタ済みの `LogStream` を返す。Textual UI が個別エージェントのログを購読する際に使用。
- `tools.log.get_logging_state()` : 現在のログ設定を参照し、エージェント固有の視点から確認できるようにする（内部でグローバルヘルパーを呼ぶ）。
- 例:
  ```python
  tools.log.logger.info("agent started")

  with tools.log.context(channel="planning", task_id="t-42"):
      tools.log.logger.debug("evaluating options")
  ```

## ランタイム制御ヘルパー

- `set_global_log_level(level: str)` : 全シンクの最小レベルを変更。
- `set_sink_level(name: str, level: str)` : 個別シンクのレベルを変更（`name` は `configure_logging` が返すハンドルを想定）。
- これらは任意の UI / CLI から呼べるよう公開するが、利用は必須ではない。

## 今後のタスク

- `LogStream` / `LogRecord` の型定義を整備し、pytest でリングバッファ購読のテストを追加する。
- TextualHumanAgent へ `LogPanelAdapter` を正式に組み込み、ログパネルの差し替えインターフェースを提供する。
- `docs/implementation_status.md` にログ基盤実装タスクの進捗を反映する。
- `get_logging_state()` の仕様とテストを整備し、開発者が動的に状態を確認できる仕組みを提供する。
