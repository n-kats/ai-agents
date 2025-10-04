from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Sequence, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field

from nkaa.framework.agent import BaseTools

OpenAI: type[Any] | None
AsyncOpenAI: type[Any] | None

try:  # pragma: no cover - openai が未インストールの場合の補助
    from openai import OpenAI as _RuntimeOpenAI
except ImportError as exc:  # pragma: no cover - 実行環境に依存
    OpenAI = None
    AsyncOpenAI = None
    _OPENAI_IMPORT_ERROR: ImportError | None = exc
    _ASYNC_OPENAI_IMPORT_ERROR: ImportError | None = exc
else:
    OpenAI = cast(type[Any], _RuntimeOpenAI)
    _OPENAI_IMPORT_ERROR = None
    try:  # pragma: no cover - 旧バージョンで AsyncOpenAI が未提供の場合
        from openai import AsyncOpenAI as _RuntimeAsyncOpenAI
    except ImportError as async_exc:
        AsyncOpenAI = None
        _ASYNC_OPENAI_IMPORT_ERROR = async_exc
    else:
        AsyncOpenAI = cast(type[Any], _RuntimeAsyncOpenAI)
        _ASYNC_OPENAI_IMPORT_ERROR = None


ParsedModelT = TypeVar("ParsedModelT", bound=BaseModel)


@dataclass
class LLMCallTool(BaseTools):
    """OpenAI Responses API を用いた gpt-5 系モデル呼び出し用ツール。"""

    default_model: str = "gpt-5-mini"
    api_key: str | None = None
    client_options: dict[str, Any] = field(default_factory=dict)
    _client: Any = field(init=False, default=None, repr=False)
    _async_client: Any = field(init=False, default=None, repr=False)

    # ------------------------------------------------------------------
    # BaseTools interface
    # ------------------------------------------------------------------
    def stop(self) -> None:
        return None

    def save(self) -> None:
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def _build_payload(
        self,
        messages: Sequence[dict[str, Any]] | Iterable[dict[str, Any]],
        *,
        model_name: str | None = None,
        response_format: ResponseFormatModel | dict[str, Any] | None = None,
        text_format: type[BaseModel] | None = None,
        max_output_tokens: int | None = None,
        **params: Any,
    ) -> tuple[dict[str, Any], bool]:
        if response_format is not None and text_format is not None:
            raise ValueError(
                "response_format と text_format は同時に指定できません。"
            )

        model = self._normalize_model(model_name)
        payload: dict[str, Any] = {
            "model": model,
            "input": list(messages),
        }
        if response_format is not None:
            payload["response_format"] = (
                response_format.model_dump(exclude_none=True, by_alias=True)
                if isinstance(response_format, BaseModel)
                else response_format
            )
        use_parse = False
        if text_format is not None:
            payload["text_format"] = text_format
            use_parse = True
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens
        if params:
            payload.update(params)
        return payload, use_parse

    def create_response(
        self,
        messages: Sequence[dict[str, Any]] | Iterable[dict[str, Any]],
        *,
        model_name: str | None = None,
        response_format: ResponseFormatModel | dict[str, Any] | None = None,
        text_format: type[BaseModel] | None = None,
        max_output_tokens: int | None = None,
        **params: Any,
    ) -> Any:
        """Responses API を呼び出し、レスポンスオブジェクトを返す。"""

        client = self._ensure_client()
        payload, use_parse = self._build_payload(
            messages,
            model_name=model_name,
            response_format=response_format,
            text_format=text_format,
            max_output_tokens=max_output_tokens,
            **params,
        )
        if use_parse:
            return client.responses.parse(**payload)
        return client.responses.create(**payload)

    async def acreate_response(
        self,
        messages: Sequence[dict[str, Any]] | Iterable[dict[str, Any]],
        *,
        model_name: str | None = None,
        response_format: ResponseFormatModel | dict[str, Any] | None = None,
        text_format: type[BaseModel] | None = None,
        max_output_tokens: int | None = None,
        **params: Any,
    ) -> Any:
        """Responses API を非同期に呼び出し、レスポンスを取得する。"""

        client = self._ensure_async_client()
        payload, use_parse = self._build_payload(
            messages,
            model_name=model_name,
            response_format=response_format,
            text_format=text_format,
            max_output_tokens=max_output_tokens,
            **params,
        )
        if use_parse:
            return await client.responses.parse(**payload)
        return await client.responses.create(**payload)

    def call_text(
        self,
        messages: Sequence[dict[str, Any]] | Iterable[dict[str, Any]],
        *,
        model_name: str | None = None,
        response_format: ResponseFormatModel | dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
        **params: Any,
    ) -> str:
        """Responses API の出力テキストのみを抽出して返す。"""

        response = self.create_response(
            messages,
            model_name=model_name,
            response_format=response_format,
            max_output_tokens=max_output_tokens,
            **params,
        )
        text = self.extract_output_text(response)
        if not text:
            raise RuntimeError("LLM から有効な出力が得られませんでした。")
        return text

    async def call_text_async(
        self,
        messages: Sequence[dict[str, Any]] | Iterable[dict[str, Any]],
        *,
        model_name: str | None = None,
        response_format: ResponseFormatModel | dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
        **params: Any,
    ) -> str:
        """Responses API の出力テキストを非同期に取得する。"""

        response = await self.acreate_response(
            messages,
            model_name=model_name,
            response_format=response_format,
            max_output_tokens=max_output_tokens,
            **params,
        )
        text = self.extract_output_text(response)
        if not text:
            raise RuntimeError("LLM から有効な出力が得られませんでした。")
        return text

    def call(
        self,
        *,
        prompt: str,
        model_name: str | None = None,
        max_output_tokens: int | None = None,
        **params: Any,
    ) -> str:
        """ワンショットのユーザープロンプトを渡してテキスト出力を得るヘルパー。"""

        messages = [{"role": "user", "content": prompt}]
        return self.call_text(
            messages,
            model_name=model_name,
            max_output_tokens=max_output_tokens,
            **params,
        )

    async def call_async(
        self,
        *,
        prompt: str,
        model_name: str | None = None,
        max_output_tokens: int | None = None,
        **params: Any,
    ) -> str:
        """ユーザープロンプトに対する応答を非同期に取得する。"""

        messages = [{"role": "user", "content": prompt}]
        return await self.call_text_async(
            messages,
            model_name=model_name,
            max_output_tokens=max_output_tokens,
            **params,
        )

    def call_json(
        self,
        messages: Sequence[dict[str, Any]] | Iterable[dict[str, Any]],
        *,
        model_name: str | None = None,
        response_format: ResponseFormatModel | dict[str, Any],
        max_output_tokens: int | None = None,
        **params: Any,
    ) -> Any:
        """Responses API の結果を JSON としてデコードして返す。"""

        text = self.call_text(
            messages,
            model_name=model_name,
            response_format=response_format,
            max_output_tokens=max_output_tokens,
            **params,
        )
        import json

        return json.loads(text)

    async def call_json_async(
        self,
        messages: Sequence[dict[str, Any]] | Iterable[dict[str, Any]],
        *,
        model_name: str | None = None,
        response_format: ResponseFormatModel | dict[str, Any],
        max_output_tokens: int | None = None,
        **params: Any,
    ) -> Any:
        """Responses API の結果を JSON として非同期にデコードする。"""

        text = await self.call_text_async(
            messages,
            model_name=model_name,
            response_format=response_format,
            max_output_tokens=max_output_tokens,
            **params,
        )

        import json

        return json.loads(text)

    def call_parsed(
        self,
        messages: Sequence[dict[str, Any]] | Iterable[dict[str, Any]],
        *,
        parse_model: type[ParsedModelT],
        model_name: str | None = None,
        max_output_tokens: int | None = None,
        **params: Any,
    ) -> ParsedModelT:
        """Responses API の構造化出力を Pydantic モデルとして取得する。"""

        response = self.create_response(
            messages,
            model_name=model_name,
            text_format=parse_model,
            max_output_tokens=max_output_tokens,
            **params,
        )
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise RuntimeError("Responses API から構造化出力が得られませんでした。")
        if isinstance(parsed, parse_model):
            return parsed
        return parse_model.model_validate(parsed)

    async def call_parsed_async(
        self,
        messages: Sequence[dict[str, Any]] | Iterable[dict[str, Any]],
        *,
        parse_model: type[ParsedModelT],
        model_name: str | None = None,
        max_output_tokens: int | None = None,
        **params: Any,
    ) -> ParsedModelT:
        """Responses API の構造化出力を非同期に取得する。"""

        response = await self.acreate_response(
            messages,
            model_name=model_name,
            text_format=parse_model,
            max_output_tokens=max_output_tokens,
            **params,
        )
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise RuntimeError("Responses API から構造化出力が得られませんでした。")
        if isinstance(parsed, parse_model):
            return parsed
        return parse_model.model_validate(parsed)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def extract_output_text(self, response: Any) -> str:
        """Responses API からテキスト出力を可能な限り抽出する。"""

        if hasattr(response, "output_text") and response.output_text:
            return str(response.output_text).strip()

        def _maybe_text(node: Any) -> str | None:
            if node is None:
                return None
            if isinstance(node, str):
                return node
            if isinstance(node, (list, tuple)):
                list_parts: list[str] = []
                for item in node:
                    maybe = _maybe_text(item)
                    if maybe:
                        list_parts.append(maybe)
                if list_parts:
                    return "\n".join(list_parts)
                return None
            if isinstance(node, dict):
                if "value" in node and isinstance(node["value"], str):
                    return node["value"]
                if "text" in node:
                    return _maybe_text(node["text"])
                if "content" in node:
                    return _maybe_text(node["content"])
                dict_parts: list[str] = []
                for value in node.values():
                    maybe = _maybe_text(value)
                    if maybe:
                        dict_parts.append(maybe)
                if dict_parts:
                    return "\n".join(dict_parts)
                return None
            if hasattr(node, "value") and isinstance(getattr(node, "value"), str):
                return str(getattr(node, "value"))
            if hasattr(node, "text"):
                return _maybe_text(getattr(node, "text"))
            if hasattr(node, "content"):
                return _maybe_text(getattr(node, "content"))
            if hasattr(node, "model_dump"):
                return _maybe_text(node.model_dump())
            return None

        collected_parts: list[str] = []

        output = getattr(response, "output", None)
        if output:
            for item in output:
                maybe = _maybe_text(getattr(item, "content", None))
                if maybe:
                    collected_parts.append(maybe)

        if not collected_parts:
            data = getattr(response, "data", None)
            if data:
                for item in data:
                    maybe = _maybe_text(getattr(item, "content", None))
                    if maybe:
                        collected_parts.append(maybe)

        if not collected_parts and hasattr(response, "choices"):
            for choice in getattr(response, "choices", []):
                maybe = _maybe_text(getattr(choice, "message", None))
                if maybe:
                    collected_parts.append(maybe)

        if not collected_parts and hasattr(response, "model_dump"):
            dumped = response.model_dump()
            maybe = _maybe_text(dumped)
            if maybe:
                collected_parts.append(maybe)

        aggregated = "\n".join(part.strip() for part in collected_parts if part)
        if aggregated.strip():
            return aggregated.strip()

        return str(response)

    def _ensure_client(self) -> Any:
        if OpenAI is None:
            raise RuntimeError(
                "openai パッケージが見つかりません。`pip install openai` を実行してください。"
            ) from _OPENAI_IMPORT_ERROR

        if self._client is None:
            api_key = self.api_key or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY が設定されていません。OpenAI の API キーを環境変数に設定してください。"
                )
            self._client = OpenAI(api_key=api_key, **self.client_options)
        return self._client

    def _ensure_async_client(self) -> Any:
        if AsyncOpenAI is None:
            raise RuntimeError(
                "openai パッケージの AsyncOpenAI が利用できません。"
            ) from _ASYNC_OPENAI_IMPORT_ERROR

        if self._async_client is None:
            api_key = self.api_key or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY が設定されていません。OpenAI の API キーを環境変数に設定してください。"
                )
            self._async_client = AsyncOpenAI(api_key=api_key, **self.client_options)
        return self._async_client

    def _normalize_model(self, model_name: str | None) -> str:
        model = model_name or self.default_model
        if not model.startswith("gpt-5"):
            raise ValueError("LLMCallTool は gpt-5 系モデルのみをサポートします。")
        return model


class JsonSchemaDefinition(BaseModel):
    """Responses API の JSON Schema 定義コンテナ。"""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    schema_body: dict[str, Any] = Field(alias="schema")


class JsonSchemaResponseFormat(BaseModel):
    """Responses API の JSON Schema フォーマット指定。"""

    type: Literal["json_schema"] = "json_schema"
    json_schema: JsonSchemaDefinition


class TextResponseFormat(BaseModel):
    """Responses API の text フォーマット指定。"""

    type: Literal["text"] = "text"


ResponseFormatModel = JsonSchemaResponseFormat | TextResponseFormat
