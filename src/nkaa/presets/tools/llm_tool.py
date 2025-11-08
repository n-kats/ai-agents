from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Sequence, TypeVar
from weakref import WeakKeyDictionary

from loguru import logger
from opik import Opik
from opik.integrations.openai import track_openai
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel, ConfigDict, Field

from nkaa.framework.agent import BaseTools


ParsedModelT = TypeVar("ParsedModelT", bound=BaseModel)


@dataclass
class LLMCallTool(BaseTools):
    """OpenAI Responses API を用いた gpt-5 系モデル呼び出し用ツール。"""

    default_model: str = "gpt-5-mini"
    api_key: str | None = None
    client_options: dict[str, Any] = field(default_factory=dict)
    debug: bool = False
    _client: Any = field(init=False, default=None, repr=False)
    _async_clients: WeakKeyDictionary[asyncio.AbstractEventLoop, Any] = field(
        init=False, default_factory=WeakKeyDictionary, repr=False
    )
    _opik_client: Opik | None = field(init=False, default=None, repr=False)
    _opik_config_signature: tuple[str | None, str | None, str | None] | None = field(
        init=False, default=None, repr=False
    )

    # ------------------------------------------------------------------
    # BaseTools interface
    # ------------------------------------------------------------------
    def stop(self) -> None:
        if self._client is not None:
            close = getattr(self._client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
            self._client = None

        for loop, client in list(self._async_clients.items()):
            aclose = getattr(client, "aclose", None)
            if callable(aclose):
                try:
                    asyncio.run(aclose())
                except RuntimeError:
                    try:
                        loop.run_until_complete(aclose())
                    except Exception:
                        pass
                except Exception:
                    pass
            else:
                close = getattr(client, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
        self._async_clients.clear()

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
        message_list = list(messages)
        self._log_debug(
            "call_parsed_async:request",
            {
                "model": model_name or self.default_model,
                "messages": message_list,
                "params": params,
            },
        )
        try:
            response = await self.acreate_response(
                message_list,
                model_name=model_name,
                text_format=parse_model,
                max_output_tokens=max_output_tokens,
                **params,
            )
        except asyncio.CancelledError:
            self._log_debug("call_parsed_async:cancelled", None)
            raise
        except Exception as exc:
            self._log_debug(
                "call_parsed_async:error",
                {"error": repr(exc)},
            )
            raise
        self._log_debug(
            "call_parsed_async:response",
            self._safe_model_dump(response),
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

        aggregated = "\n".join(part.strip()
                               for part in collected_parts if part)
        if aggregated.strip():
            return aggregated.strip()

        return str(response)

    def _safe_model_dump(self, response: Any) -> Any:
        if hasattr(response, "model_dump"):
            try:
                return response.model_dump()
            except Exception:  # pragma: no cover - デバッグ用途
                return repr(response)
        return repr(response)

    def _log_debug(self, label: str, payload: Any) -> None:
        if not self.debug:
            return
        if payload is None:
            logger.debug(label)
            return
        try:
            serialized = json.dumps(
                payload, ensure_ascii=False, default=lambda obj: repr(obj))
        except TypeError:  # pragma: no cover - デバッグ用途
            serialized = repr(payload)
        logger.debug("{} {}", label, serialized)

    def _ensure_client(self) -> Any:
        if self._client is None:
            api_key = self.api_key or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY が設定されていません。OpenAI の API キーを環境変数に設定してください。"
                )
            self._client = OpenAI(api_key=api_key, **self.client_options)
            self._client = self._configure_opik_tracking(self._client)
        return self._client

    def _ensure_async_client(self) -> Any:
        loop = asyncio.get_running_loop()
        client = self._async_clients.get(loop)
        if client is not None:
            return client

        api_key = self.api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY が設定されていません。OpenAI の API キーを環境変数に設定してください。"
            )
        client = AsyncOpenAI(api_key=api_key, **self.client_options)
        client = self._configure_opik_tracking(client)
        # 各エージェントはスレッドごとに独立したイベントループを持つため、
        # ループ間で AsyncOpenAI を共有すると `RuntimeError` が発生する。
        # ループごとにクライアントをキャッシュし、再利用ループでのみ共有する。
        self._async_clients[loop] = client
        return client

    def _configure_opik_tracking(self, openai_client: Any) -> Any:
        opik_client = self._ensure_opik_client()
        if opik_client is None:
            return openai_client
        project_name = getattr(opik_client, "project_name", None)
        try:
            patched = track_openai(openai_client, project_name=project_name)
            return patched or openai_client
        except TypeError as exc:  # pragma: no cover - 互換性確保のためのフォールバック
            logger.debug("track_openai fallback without project_name: {}", repr(exc))
            patched = track_openai(openai_client)
            return patched or openai_client
        except Exception as exc:  # pragma: no cover - 想定外の失敗は記録のみ
            logger.debug("track_openai failed: {}", repr(exc))
            return openai_client

    def _ensure_opik_client(self) -> Opik | None:
        url = os.getenv("NKAA_OPIK_URL")
        if not url:
            self._opik_client = None
            self._opik_config_signature = None
            return None
        project = os.getenv("NKAA_OPIK_PROJECT_NAME") or None
        signature = (url, project)
        if self._opik_client is not None and self._opik_config_signature == signature:
            return self._opik_client
        try:
            os.environ["OPIK_URL"] = url
            os.environ["OPIK_URL_OVERRIDE"] = url
            self._opik_client = Opik(project_name=project, host=url)
            self._opik_config_signature = signature
        except Exception as exc:  # pragma: no cover - 接続エラー時はロギングのみ
            logger.debug("Opik client initialization failed: {}", repr(exc))
            self._opik_client = None
            self._opik_config_signature = None
        return self._opik_client

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
