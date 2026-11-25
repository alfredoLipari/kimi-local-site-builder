"""Step 1: turn raw facts into a design brief with Structured Output.

The brief is the one place where the model is asked to have an opinion. It is
JSON with a strict schema, so step 2 can rely on every field being there.
"""

from __future__ import annotations

import json
from typing import Any

from .kimi import Kimi

SECTION_IDS = ["hero", "about", "menu", "reviews", "hours", "contact"]

_STR = {"type": "string"}

BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["concept", "tone", "palette", "fonts", "hero", "sections"],
    "properties": {
        "concept": {**_STR, "description": "One sentence: the idea that makes this site belong to this business and no other."},
        "tone": {**_STR, "description": "How the copy should sound, in a few words."},
        "palette": {
            "type": "object",
            "additionalProperties": False,
            "required": ["background", "surface", "text", "accent"],
            "properties": {k: {**_STR, "description": "Hex colour, e.g. #1b1b1b"} for k in ["background", "surface", "text", "accent"]},
        },
        "fonts": {
            "type": "object",
            "additionalProperties": False,
            "required": ["display", "body"],
            "properties": {
                "display": {**_STR, "description": "CSS font-family stack for headings, system fonts only."},
                "body": {**_STR, "description": "CSS font-family stack for text, system fonts only."},
            },
        },
        "hero": {
            "type": "object",
            "additionalProperties": False,
            "required": ["headline", "subline", "cta_label"],
            "properties": {"headline": _STR, "subline": _STR, "cta_label": _STR},
        },
        "sections": {
            "type": "array",
            "description": "Sections to build, in page order. Leave out a section when the facts cannot fill it.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "title", "purpose"],
                "properties": {
                    "id": {"type": "string", "enum": SECTION_IDS},
                    "title": _STR,
                    "purpose": {**_STR, "description": "What this section must do for a visitor, in one sentence."},
                },
            },
        },
    },
}

SYSTEM = """You are the art director of a small studio that builds one-page websites for local businesses.
You receive FACTS: everything publicly known about one business, as JSON.
Write the design brief for its site.

- The concept comes from what is specific to this business in FACTS (a dish, a street, a habit customers mention), not from its category.
- Write all copy in the language given by FACTS.language.
- Use only what FACTS says. Never add prices, opening hours, awards, years or claims that are not in FACTS.
- Plan a section only if FACTS has the content for it."""


def make_brief(kimi: Kimi, facts: dict[str, Any]) -> dict[str, Any]:
    reply = kimi.chat(
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "FACTS:\n" + json.dumps(facts, ensure_ascii=False, indent=2)},
        ],
        effort="high",
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "site_brief", "strict": True, "schema": BRIEF_SCHEMA},
        },
    )
    # Parse message.content only; reasoning_content is never part of the answer.
    return json.loads(reply.content)
