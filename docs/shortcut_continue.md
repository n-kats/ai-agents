# 続けて対応時に即参照すべき資料

このメモは、ユーザーから「続けて」と指示された際に必要な情報へ素早く辿り着くためのショートカットです。主にチャンネル検索フローの継続作業で確認した内容をまとめています。

## 1. 全体構造と進捗の確認
- `docs/directory_structure.md` : どのディレクトリに関連資料があるかを把握するために最初に確認。
- `docs/implementation_status.md` : チャンネル検索／参加周りのチェック項目が更新されているので、未完タスクの把握に必須。

## 2. チャンネル仕様と既存決定事項
- `docs/channel_spec.md` : `ChannelManager.search_channels` や `ChannelTools.join_matching` の振る舞い、および残課題（アクセス制御や検索条件拡張など）の整理を確認。

## 3. コア実装の読みどころ
- `nkaa/framework/channels/manager.py` : `search_channels` を含むマネージャの中核ロジック。未読キュー復元やメンバーシップ管理の流れもここで把握。
- `nkaa/framework/channels/models.py` : `ChannelSearchQuery` のフィルタ条件定義。どのメタデータ項目が検索条件になるかの参照用。
- `nkaa/framework/channels/repository.py` : InMemory/SQL 実装が `search` と連携するために必要な永続層の仕組みを確認。
- `nkaa/framework/tools.py` : `ChannelTools.search` と `join_matching` のエージェント向け API。検索結果と参加処理の利用例を把握。

## 4. テストの参照ポイント
- `tests/framework/test_channels.py` : チャンネル検索・自動参加のテストケース `test_channel_search_and_auto_join` を確認し、期待挙動を具体例で把握。

## 使い方メモ
- 作業を再開する際は 1 → 4 の順で目を通すと、全体状況 → 仕様 → 実装 → テストの流れを最短で復習できる。
- 新しい検索条件やフローを追加する場合は、上記ファイルに加えてドキュメントの更新箇所を `docs/channel_spec.md` → `docs/implementation_status.md` の順に検討する。
