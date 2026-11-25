"""Thin wrapper around the Kimi API (OpenAI-compatible chat completions).

Everything Kimi-specific in this project lives here, so the rest of the code
reads as plain pipeline logic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

BASE_URL = os.environ.get("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")
DEFAULT_MODEL = os.environ.get("KIMI_MODEL", "kimi-k3")


@dataclass
class Usage:
    """Token totals across every call of a run, so a build can report its cost."""

    calls: int = 0
    prompt: int = 0
    cached: int = 0
    completion: int = 0
    reasoning: int = 0

    def add(self, usage: Any) -> None:
        if usage is None:
            return
        self.calls += 1
        self.prompt += _get(usage, "prompt_tokens") or 0
        self.completion += _get(usage, "completion_tokens") or 0
        self.cached += _get(_get(usage, "prompt_tokens_details"), "cached_tokens") or 0
        self.reasoning += _get(_get(usage, "completion_tokens_details"), "reasoning_tokens") or 0

    def as_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt,
            "cached_prompt_tokens": self.cached,
            "completion_tokens": self.completion,
            "reasoning_tokens": self.reasoning,
        }


@dataclass
class Reply:
    """One assistant turn. `message` is the full dict to append to the history."""

    content: str
    reasoning: str
    tool_calls: list[dict[str, Any]]
    finish_reason: str | None
    message: dict[str, Any] = field(repr=False)


class Kimi:
    def __init__(self, client: Any = None, model: str | None = None) -> None:
        if client is None:
            from openai import OpenAI

            key = os.environ.get("MOONSHOT_API_KEY")
            if not key:
                raise SystemExit("Set MOONSHOT_API_KEY (create one at https://platform.kimi.ai).")
            client = OpenAI(api_key=key, base_url=BASE_URL)
        self.client = client
        self.model = model or DEFAULT_MODEL
        self.usage = Usage()

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        effort: str = "low",
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        response_format: dict[str, Any] | None = None,
        max_completion_tokens: int | None = None,
        on_delta: Callable[[str, str], None] | None = None,
    ) -> Reply:
        """Send one request. With `on_delta`, the reply is streamed and the
        callback receives ("reasoning" | "content", text) as chunks arrive."""
        params: dict[str, Any] = {"model": self.model, "messages": messages}
        # K3 always thinks; reasoning_effort (low | high | max) is the only dial,
        # and the default is max. Sampling parameters are fixed on K3, so none are sent.
        if self.model.startswith("kimi-k3"):
            params["reasoning_effort"] = effort
        if tools:
            params["tools"] = tools
        if tool_choice is not None:
            params["tool_choice"] = tool_choice
        if response_format:
            params["response_format"] = response_format
        if max_completion_tokens:
            params["max_completion_tokens"] = max_completion_tokens

        if on_delta is None:
            completion = self.client.chat.completions.create(**params)
            self.usage.add(_get(completion, "usage"))
            choice = completion.choices[0]
            msg = choice.message
            tool_calls = [_tool_call(t) for t in (_get(msg, "tool_calls") or [])]
            return _reply(_get(msg, "content"), _get(msg, "reasoning_content"), tool_calls, choice.finish_reason)

        stream = self.client.chat.completions.create(
            **params, stream=True, stream_options={"include_usage": True}
        )
        content: list[str] = []
        reasoning: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        finish = None
        for chunk in stream:
            if _get(chunk, "usage"):
                self.usage.add(chunk.usage)  # final chunk: choices == []
            for choice in _get(chunk, "choices") or []:
                delta = choice.delta
                if text := _get(delta, "reasoning_content"):
                    reasoning.append(text)
                    on_delta("reasoning", text)
                if text := _get(delta, "content"):
                    content.append(text)
                    on_delta("content", text)
                for part in _get(delta, "tool_calls") or []:
                    call = calls.setdefault(part.index, {"id": "", "name": "", "arguments": ""})
                    call["id"] = _get(part, "id") or call["id"]
                    fn = _get(part, "function")
                    call["name"] += _get(fn, "name") or ""
                    call["arguments"] += _get(fn, "arguments") or ""
                finish = choice.finish_reason or finish
        return _reply("".join(content), "".join(reasoning), [calls[i] for i in sorted(calls)], finish)


def _reply(content: str | None, reasoning: str | None, tool_calls: list[dict[str, Any]], finish: str | None) -> Reply:
    # The history must carry the complete assistant message: content, tool calls
    # and reasoning_content. Dropping the reasoning loses the model's context.
    message: dict[str, Any] = {"role": "assistant", "content": content or ""}
    if reasoning:
        message["reasoning_content"] = reasoning
    if tool_calls:
        message["tool_calls"] = [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
            for c in tool_calls
        ]
    return Reply(content or "", reasoning or "", tool_calls, finish, message)


def _tool_call(call: Any) -> dict[str, Any]:
    fn = _get(call, "function")
    return {"id": _get(call, "id"), "name": _get(fn, "name"), "arguments": _get(fn, "arguments") or "{}"}


def _get(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)
