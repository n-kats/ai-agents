# Makefile コマンド一覧

本ドキュメントは、Makefileで使用可能なコマンドとその概要を表形式でまとめています。  
詳細なポリシーやドキュメントの書き方については [docs/guides/makefile_policy.md](../guides/makefile_policy.md) を参照してください。

| コマンド       | 説明                                                         |
|----------------|--------------------------------------------------------------|
| `make lint`    | TARGETディレクトリに対して、ruffによる静的解析とmypyによる型チェックを実行 |
| `make format`  | TARGETディレクトリ内のコードをruff formatで整形し、ruff check --fixで自動修正を試みる |
| `make test`    | pytestを用いてテストスイートを実行                           |
| `make test_with_api` | `--run-live-api` オプション付きでpytestを実行し、外部LLM APIを呼ぶテストを有効化 |
