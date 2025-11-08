from __future__ import annotations

import json
import shlex
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field

from nkaa.framework.agent import AgentConfig, BaseAgent, BaseTools
from nkaa.framework.channels.models import ChannelMessage
from nkaa.framework.persistence import JsonLinesStateMixin
from nkaa.framework.tools import ChannelTools, MessageTools


class StdIOHumanHistoryRecord(BaseModel):
    channel_id: str
    direction: Literal["incoming", "outgoing"]
    payload: Any
    request_id: str | None = None


class StdIOHumanHistory(JsonLinesStateMixin[StdIOHumanHistoryRecord]):
    """標準入出力エージェント向けの履歴管理クラス。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._sequence: list[StdIOHumanHistoryRecord] = []
        self._records_by_channel: dict[str, list[StdIOHumanHistoryRecord]] = defaultdict(list)
        self.load()

    def append(self, record: StdIOHumanHistoryRecord) -> None:
        self._sequence.append(record)
        self._records_by_channel[record.channel_id].append(record)

    def records(self) -> list[StdIOHumanHistoryRecord]:
        return list(self._sequence)

    def records_for_channel(self, channel_id: str) -> list[StdIOHumanHistoryRecord]:
        return list(self._records_by_channel.get(channel_id, []))

    def get_state_path(self) -> Path:
        return self._path

    def state_model_type(self) -> type[StdIOHumanHistoryRecord]:
        return StdIOHumanHistoryRecord

    def serialize_state(self) -> Iterable[StdIOHumanHistoryRecord]:
        return list(self._sequence)

    def apply_loaded_state(self, items: list[StdIOHumanHistoryRecord]) -> None:
        self._sequence = list(items)
        self._records_by_channel = defaultdict(list)
        for record in self._sequence:
            self._records_by_channel[record.channel_id].append(record)


@dataclass
class StdIOHumanAgentTools(BaseTools):
    channels: ChannelTools
    messages: MessageTools

    def stop(self) -> None:
        self.channels.stop()
        self.messages.stop()

    def save(self) -> None:
        self.channels.save()
        self.messages.save()


class StdIOHumanAgent(BaseAgent[StdIOHumanAgentTools]):
    """標準入出力経由で人間をエージェントとして参加させる軽量実装。"""

    def __init__(
        self,
        agent_id: str,
        *,
        response_role: str = "human",
        message_field: str = "prompt",
        request_id_key: str = "request_id",
        history_path: Path | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.response_role = response_role
        self.message_field = message_field
        self.request_id_key = request_id_key
        self._request_index = 1
        self._history: StdIOHumanHistory | None = (
            StdIOHumanHistory(history_path) if history_path is not None else None
        )
        self._stop_requested = False
        self._current_send_channels: list[str] = []

    def run(self, tools: StdIOHumanAgentTools) -> None:
        self._print_usage()

        handled_message = self._process_incoming_messages(tools)

        self._initialize_send_targets(tools)
        self._print_current_targets(tools)

        if not handled_message:
            print("[StdIOHumanAgent] 受信待ちです。必要に応じてメッセージやコマンドを入力してください。", flush=True)

        while not self._stop_requested:
            message = tools.messages.read()
            if message is None:
                handled = self._handle_main_prompt(tools)
                if not handled:
                    time.sleep(0.2)
                continue

            self._append_history(
                StdIOHumanHistoryRecord(
                    channel_id=message.channel_id,
                    direction="incoming",
                    payload=message.payload,
                    request_id=self._extract_request_id(message),
                )
            )
            channel_name = tools.channels.get_channel_name(message.channel_id)
            self._display_message(message, channel_name)
            self._handle_reply(tools, message)
            self._print_current_targets(tools)

    def stop(self) -> None:
        self._stop_requested = True

    def load(self) -> None:
        if self._history is not None:
            self._history.load()

    def save(self) -> None:
        if self._history is not None:
            self._history.save()

    def _send_payload(
        self,
        tools: StdIOHumanAgentTools,
        channel_id: str,
        content: str,
        *,
        replied_message: ChannelMessage | None = None,
    ) -> None:
        content = content.strip()
        if not content:
            return

        request_id = None
        if replied_message is not None and isinstance(replied_message.payload, dict):
            request_id = replied_message.payload.get(self.request_id_key)
        if not request_id:
            request_id = self._generate_request_id()

        payload: dict[str, Any] = {
            "role": self.response_role,
            self.request_id_key: request_id,
            self.message_field: content,
        }

        tools.messages.send(channel_id, payload)
        channel_name = tools.channels.get_channel_name(channel_id)
        print(
            f"[StdIOHumanAgent] チャンネル '{channel_name}' へ request_id={request_id} を送信しました。",
            flush=True,
        )
        self._append_history(
            StdIOHumanHistoryRecord(
                channel_id=channel_id,
                direction="outgoing",
                payload=payload,
                request_id=request_id,
            )
        )

    # ------------------------------------------------------------------
    # Incoming handling
    # ------------------------------------------------------------------
    def _process_incoming_messages(self, tools: StdIOHumanAgentTools) -> bool:
        handled = False
        while True:
            message = tools.messages.read()
            if message is None:
                break
            if self._stop_requested:
                break

            handled = True
            channel_name = tools.channels.get_channel_name(message.channel_id)
            self._append_history(
                StdIOHumanHistoryRecord(
                    channel_id=message.channel_id,
                    direction="incoming",
                    payload=message.payload,
                    request_id=self._extract_request_id(message),
                )
            )
            self._display_message(message, channel_name)
            self._handle_reply(tools, message)
        return handled

    def _display_message(self, message: ChannelMessage, channel_name: str) -> None:
        print(
            f"[StdIOHumanAgent] 受信チャンネル: {channel_name} ({message.channel_id})",
            flush=True,
        )
        formatted = self._format_payload(message.payload)
        for line in formatted.splitlines():
            print(f"  {line}", flush=True)

    def _format_payload(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        try:
            return json.dumps(payload, ensure_ascii=False, indent=2)
        except TypeError:
            return repr(payload)

    def _safe_input(self, prompt: str) -> str:
        try:
            return input(prompt)
        except EOFError:
            return ""

    def _print_usage(self) -> None:
        print(
            "[StdIOHumanAgent] 利用方法: 受信メッセージを確認後、表示されるプロンプトに返信内容を入力してください。",
            flush=True,
        )
        print(
            "[StdIOHumanAgent] コマンド: '/channels' で参加チャネル一覧を表示できます。",
            flush=True,
        )
        print(
            "[StdIOHumanAgent] '/channel <name ...>' で送信先を変更できます。",
            flush=True,
        )
        print(
            "[StdIOHumanAgent] '/skip' は送信や返信をスキップし、'/help' でこの案内を再表示します。",
            flush=True,
        )

    def _initialize_send_targets(self, tools: StdIOHumanAgentTools) -> None:
        # 初期状態では参加済みチャネルすべてを送信対象とする。
        self._current_send_channels = []

    def _print_current_targets(self, tools: StdIOHumanAgentTools) -> None:
        print(
            f"[StdIOHumanAgent] 現在の送信先: {self._format_targets(tools)}",
            flush=True,
        )

    def _format_targets(self, tools: StdIOHumanAgentTools) -> str:
        metadata = {meta.id: meta for meta in tools.channels.joined_channel_metadata()}
        targets = self._effective_targets(metadata)
        if not targets:
            return "なし"
        names = []
        for channel_id in targets:
            meta = metadata.get(channel_id)
            name = meta.name or meta.id if meta is not None else channel_id
            names.append(name)
        return ", ".join(names)

    def _handle_main_prompt(self, tools: StdIOHumanAgentTools) -> bool:
        prompt = "[StdIOHumanAgent] メッセージまたはコマンド（送信先: %s）: " % self._format_targets(tools)
        text = self._safe_input(prompt)
        if not text:
            return False
        content = text.strip()
        if not content:
            return False
        if content.startswith("/"):
            self._handle_command(content, tools)
            return True
        self._send_to_targets(tools, content)
        return True

    def _handle_command(self, command: str, tools: StdIOHumanAgentTools) -> None:
        if command == "/skip":
            print("[StdIOHumanAgent] 入力をスキップしました。", flush=True)
            return
        if command == "/channels":
            self._list_channels(tools)
            return
        if command.startswith("/channel"):
            args = command[len("/channel") :].strip()
            self._set_send_targets(args, tools)
            return
        if command == "/help":
            self._print_usage()
            self._print_current_targets(tools)
            return
        print(f"[StdIOHumanAgent] 未対応のコマンドです: {command}", flush=True)

    def _list_channels(self, tools: StdIOHumanAgentTools) -> None:
        metadata = tools.channels.joined_channel_metadata()
        if not metadata:
            print("[StdIOHumanAgent] 参加チャネルがありません。", flush=True)
            return
        current = set(self._effective_targets({meta.id: meta for meta in metadata}))
        print("[StdIOHumanAgent] 参加チャネル一覧 (*は送信対象):", flush=True)
        for meta in metadata:
            name = meta.name or meta.id
            description = meta.description or ""
            mark = "*" if meta.id in current else "-"
            print(f"  {mark} {name} ({meta.id}) {description}", flush=True)

    def _set_send_targets(self, args: str, tools: StdIOHumanAgentTools) -> None:
        metadata = tools.channels.joined_channel_metadata()
        if not metadata:
            print("[StdIOHumanAgent] 参加チャネルがありません。", flush=True)
            return

        if not args:
            print("[StdIOHumanAgent] 送信先を指定してください。", flush=True)
            return

        try:
            parts = shlex.split(args)
        except ValueError as exc:
            print(f"[StdIOHumanAgent] 解析に失敗しました: {exc}", flush=True)
            return

        if not parts:
            print("[StdIOHumanAgent] 送信先を指定してください。", flush=True)
            return

        if any(part in {"*", "all"} for part in parts):
            self._current_send_channels = []
            self._print_current_targets(tools)
            return

        id_lookup = {meta.id: meta for meta in metadata}
        name_lookup = {meta.name: meta for meta in metadata if meta.name}

        selected: list[str] = []
        for token in parts:
            meta = id_lookup.get(token)
            if meta is None:
                meta = name_lookup.get(token)
            if meta is None:
                print(f"[StdIOHumanAgent] 未参加のチャネルです: {token}", flush=True)
                return
            if meta.id not in selected:
                selected.append(meta.id)

        if not selected:
            print("[StdIOHumanAgent] 有効なチャネルが選択されませんでした。", flush=True)
            return

        self._current_send_channels = selected
        self._print_current_targets(tools)

    def _send_to_targets(self, tools: StdIOHumanAgentTools, content: str) -> None:
        metadata = {meta.id: meta for meta in tools.channels.joined_channel_metadata()}
        targets = self._effective_targets(metadata)
        if not targets:
            print("[StdIOHumanAgent] 送信可能なチャネルがありません。", flush=True)
            return
        for channel_id in targets:
            self._send_payload(tools, channel_id, content)

    def _effective_targets(self, metadata: dict[str, Any]) -> list[str]:
        if self._current_send_channels:
            return [channel_id for channel_id in self._current_send_channels if channel_id in metadata]
        return [channel_id for channel_id in metadata]

    def _generate_request_id(self) -> str:
        request_id = f"input-{self._request_index:03d}"
        self._request_index += 1
        return request_id

    def _extract_request_id(self, message: ChannelMessage) -> str | None:
        payload = message.payload
        if isinstance(payload, dict):
            candidate = payload.get(self.request_id_key)
            if isinstance(candidate, str):
                return candidate
        return None

    def _append_history(self, record: StdIOHumanHistoryRecord) -> None:
        if self._history is not None:
            self._history.append(record)

    def _handle_reply(self, tools: StdIOHumanAgentTools, message: ChannelMessage) -> None:
        prompt = "[StdIOHumanAgent] 返信を入力してください（/skip でスキップ）: "
        while True:
            reply = self._safe_input(prompt).strip()
            if not reply:
                print("[StdIOHumanAgent] 空行は送信できません。/skip でスキップできます。", flush=True)
                continue

            if reply.startswith("/"):
                command = reply[1:].strip().lower()
                if command == "skip":
                    print("[StdIOHumanAgent] 返信をスキップしました。", flush=True)
                    return
                print(
                    f"[StdIOHumanAgent] 未対応のコマンドです: {reply}",
                    flush=True,
                )
                continue

            self._send_payload(
                tools,
                message.channel_id,
                reply,
                replied_message=message,
            )
            return

class StdIOHumanAgentConfig(AgentConfig):
    type: Literal["stdio_human"] = "stdio_human"
    response_role: str = Field("human", description="送信時の role フィールド値")
    message_field: str = Field("prompt", description="送信ペイロードに格納するメッセージフィールド名")
    request_id_key: str = Field("request_id", description="要求 ID を表すフィールド名")
    history_dir: Path | None = Field(
        default=None,
        description="履歴ファイルを保存するディレクトリ（未指定なら履歴を保持しない）",
    )

    def build(self) -> StdIOHumanAgent:
        history_path = None
        if self.history_dir is not None:
            history_path = self.history_dir / f"{self.id}_history.jsonl"
        return StdIOHumanAgent(
            agent_id=self.id,
            response_role=self.response_role,
            message_field=self.message_field,
            request_id_key=self.request_id_key,
            history_path=history_path,
        )


__all__ = [
    "StdIOHumanAgent",
    "StdIOHumanAgentTools",
    "StdIOHumanAgentConfig",
    "StdIOHumanHistory",
    "StdIOHumanHistoryRecord",
]
