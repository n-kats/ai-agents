"""LLMCallTool を利用して Responses API を呼び出す対話型サンプル。

実行手順:
    1. `pip install openai`
    2. `OPENAI_API_KEY` に OpenAI の API キーを設定
    3. `python samples/llm_call_tool_interactive.py` を起動し、案内に従ってプロンプトを入力
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Iterable

from pydantic import BaseModel, Field
from dotenv import load_dotenv

from nkaa.presets.tools import LLMCallTool
load_dotenv(override=True)

class GuidanceResponse(BaseModel):
    """Responses API の構造化出力を検証するためのサンプルスキーマ。"""

    title: str
    summary: str
    bullet_points: list[str] = Field(default_factory=list)


@dataclass
class DemoConfig:
    model: str
    prompt: str
    system_prompt: str = (
        "You are an assistant that returns concise structured guidance.\n"
        "Summarize the user's request, provide a short title, and list 2-4 bullet points.\n"
        "Keep bullet points short and actionable."
    )


def build_messages(config: DemoConfig) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": config.system_prompt},
        {"role": "user", "content": config.prompt},
    ]


def call_llm(tool: LLMCallTool, *, messages: Iterable[dict[str, Any]], model: str) -> GuidanceResponse:
    """LLMCallTool の call_parsed API を用いて構造化レスポンスを取得する。"""

    response = tool.call_parsed(
        list(messages),
        parse_model=GuidanceResponse,
        model_name=model,
    )
    return response


def main() -> None:
    parser = argparse.ArgumentParser(description="LLMCallTool の動作確認用対話型サンプル")
    parser.add_argument(
        "--model",
        default="gpt-5-mini",
        help="呼び出すモデル名（デフォルト: gpt-5-mini）。",
    )
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit(
            "OPENAI_API_KEY が未設定です。OpenAI の API キーを環境変数に設定してから実行してください。"
        )

    try:
        prompt = input("LLM へ渡す指示を入力してください: ").strip()
    except EOFError:
        raise SystemExit("標準入力からプロンプトを読み取れませんでした。") from None
    if not prompt:
        raise SystemExit("空のプロンプトは指定できません。")

    config = DemoConfig(model=args.model, prompt=prompt)
    tool = LLMCallTool()

    messages = build_messages(config)
    print(f"OpenAI model={config.model} へリクエストを送信します…")
    response = call_llm(tool, messages=messages, model=config.model)

    print("\n=== 応答 (GuidanceResponse) ===")
    print(json.dumps(response.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
