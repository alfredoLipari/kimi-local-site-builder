"""Step 4: conversational edits through tool calls.

An owner asks for a change in plain words. The model sees the whole page but
answers with small tool calls (swap one section, add one, change a design
token), so an edit costs a section's worth of output, not a page's.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from . import page
from .kimi import Kimi

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "replace_section",
            "description": "Replace one existing section of the page with new HTML.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["section_id", "html"],
                "properties": {
                    "section_id": {"type": "string", "description": "The data-section id of the section to replace."},
                    "html": {"type": "string", "description": 'The complete new <section data-section="..."> element, same id.'},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_section",
            "description": "Add a new section right after an existing one.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["after_section_id", "html"],
                "properties": {
                    "after_section_id": {"type": "string", "description": "The data-section id the new section follows."},
                    "html": {"type": "string", "description": 'One complete <section data-section="new-id"> element with a new id.'},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_css_variables",
            "description": "Change design tokens (colours, fonts, spacing) defined as CSS custom properties in :root.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["variables"],
                "properties": {
                    "variables": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name", "value"],
                            "properties": {
                                "name": {"type": "string", "description": "Custom property name, e.g. --accent"},
                                "value": {"type": "string"},
                            },
                        },
                    }
                },
            },
        },
    },
]

SYSTEM = """You maintain the one-page website of a local business. The owner asks for a change in plain words.

- Make the change with the tools. Touch only what the request needs: one section, or the design tokens.
- Keep the page's structure: every block is a <section data-section="id">, styles use the CSS custom properties in :root.
- Keep the page's language.
- State only what is in FACTS or in the owner's request. Never add prices, opening hours, phone numbers, ratings, years or links from anywhere else. If the request needs a fact you do not have, leave it out and say which one.
- When the change is done, answer the owner in one short sentence in their language. No HTML in that answer."""


def _apply(html: str, name: str, args: dict[str, Any]) -> str:
    if name == "replace_section":
        return page.replace_section(html, args["section_id"], args["html"])
    if name == "insert_section":
        return page.insert_section(html, args["after_section_id"], args["html"])
    if name == "set_css_variables":
        return page.set_css_variables(html, {v["name"]: v["value"] for v in args["variables"]})
    raise ValueError(f"unknown tool '{name}'")


def edit_page(
    kimi: Kimi,
    html: str,
    facts: dict[str, Any],
    request: str,
    *,
    max_rounds: int = 6,
    on_tool: Callable[[str, dict[str, Any], str | None], None] | None = None,
) -> tuple[str, str]:
    """Apply one request. Returns (new_html, the model's closing sentence)."""
    # Stable content first (rules, facts, page), the request last: consecutive
    # edits of the same page then share a long prefix that the API can serve
    # from its context cache.
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": "FACTS:\n"
            + json.dumps(facts, ensure_ascii=False, indent=2)
            + "\n\nPAGE:\n"
            + html
            + "\n\nREQUEST:\n"
            + request,
        },
    ]
    for round_no in range(max_rounds):
        reply = kimi.chat(
            messages,
            effort="low",
            tools=TOOLS,
            # The first turn must act, not chat. Models other than K3 keep the default.
            tool_choice="required" if round_no == 0 and kimi.model.startswith("kimi-k3") else None,
        )
        messages.append(reply.message)
        if not reply.tool_calls:
            return html, reply.content.strip()
        for call in reply.tool_calls:
            error = None
            try:
                args = json.loads(call["arguments"] or "{}")
                html = _apply(html, call["name"], args)
            except (KeyError, ValueError, TypeError) as exc:  # the model gets to read the error and retry
                args, error = {}, str(exc).strip("'\"")
            if on_tool:
                on_tool(call["name"], args, error)
            result = {"ok": True, "sections": list(page.sections(html))} if error is None else {"ok": False, "error": error}
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)})
    return html, ""
