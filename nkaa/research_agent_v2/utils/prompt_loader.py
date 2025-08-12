import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# プロンプトディレクトリのパスを取得 (このファイルの位置基準)
# main.py から実行されることを想定し、main.py からの相対パスで考える方が安定する可能性もある
# ここでは utils ディレクトリからの相対パスで prompts を探す
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt_template(template_name: str) -> str:
    """
    指定された名前のプロンプトテンプレートファイルを prompts ディレクトリから読み込む。
    ファイル名は {template_name}.j2 であると想定する。

    Args:
        template_name: 読み込むテンプレートの名前 (拡張子 .j2 は除く)。

    Returns:
        テンプレートファイルの内容文字列。

    Raises:
        FileNotFoundError: 指定されたテンプレートファイルが見つからない場合。
        Exception: ファイル読み込み中に他のエラーが発生した場合。
    """
    if not template_name.endswith(".j2"):
        filename = f"{template_name}.j2"
    else:
        filename = template_name  # すでに .j2 が付いている場合

    filepath = PROMPTS_DIR / filename

    logger.debug(f"プロンプトテンプレートを読み込みます: {filepath}")

    if not filepath.is_file():
        logger.error(f"プロンプトテンプレートファイルが見つかりません: {filepath}")
        raise FileNotFoundError(
            f"プロンプトテンプレートファイルが見つかりません: {filepath}"
        )

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(
            f"プロンプトテンプレートファイル '{filepath}' の読み込み中にエラーが発生しました: {e}",
            exc_info=True,
        )
        raise
