import logging
import os
from typing import Any, Callable, ParamSpec, TypeVar

from jinja2 import Environment, FileSystemLoader, select_autoescape

# 型変数とパラメータ仕様を定義
T = TypeVar("T")
P = ParamSpec("P")


def safe_execute(func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T | None:
    """指定された関数を安全に実行し、例外発生時にはエラーログを出力して None を返す。

    Args:
        func: 実行する関数。
        *args: 関数に渡す位置引数。
        **kwargs: 関数に渡すキーワード引数。

    Returns:
        関数の実行結果、または例外発生時は None。
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        # 例外発生時はエラーログを出力し、処理の継続を可能にするために None を返す設計。
        # Why not: 例外を再送出すると呼び出し元でのエラーハンドリングが必須になるため、
        #          ここでは None を返すことでより柔軟なエラー処理を可能にする。
        logging.error(
            f"Error occurred during safe execution of {func.__name__}: {e}",
            exc_info=True,
        )  # exc_info=True でスタックトレースも記録
        return None


def create_mock_object(name: str, **kwargs: Any) -> object:
    """ユニットテストで使用するためのシンプルなモックオブジェクトを生成する。

    指定された属性を持つダミーオブジェクトを作成する。複雑なモックが必要な場合は
    unittest.mock などの専用ライブラリの使用を検討すること。

    Args:
        name: モックオブジェクトの識別に使う名前（主に repr 用）。
        **kwargs: モックオブジェクトに設定する属性。

    Returns:
        指定された属性を持つモックオブジェクト。
    """

    class MockObject:
        def __init__(self, **attrs: Any):
            self.__dict__.update(attrs)

        def __repr__(self) -> str:
            # デバッグ時に分かりやすい表現を返す
            return f"<MockObject {name}: {self.__dict__}>"

    return MockObject(**kwargs)


# --- Jinja2 Environment Setup ---
# プロンプトテンプレート (.j2 ファイル) が格納されているディレクトリを設定
# __file__ はこの utils.py のパスを指すため、prompts ディレクトリへの相対パスを正しく指定
PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")
# Jinja2 環境を初期化。FileSystemLoader を使用してテンプレートをロードする
jinja_env = Environment(
    loader=FileSystemLoader(PROMPT_DIR),
    autoescape=select_autoescape(),  # HTMLエスケープを有効化 (必須ではないが安全のため)
)


def load_prompt(template_name: str, **kwargs) -> str:
    """指定された Jinja2 テンプレートを読み込み、与えられた変数でレンダリングする。"""
    template = jinja_env.get_template(template_name)
    return template.render(**kwargs)


# ここに他の汎用的なユーティリティ関数を追加していく
