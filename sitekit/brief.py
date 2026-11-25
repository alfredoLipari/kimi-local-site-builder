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
    "required": ["concept", "tone", "palette", "fonts", "art_direction", "hero", "sections"],
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
            "required": ["display", "body", "why"],
            "properties": {
                "display": {**_STR, "description": "Google Fonts family for headlines, exact name, e.g. Fraunces."},
                "body": {**_STR, "description": "Google Fonts family for text, exact name."},
                "why": {**_STR, "description": "Why this pairing fits the concept, in one sentence."},
            },
        },
        "art_direction": {
            "type": "object",
            "additionalProperties": False,
            "required": ["layout", "hero", "signature", "motion"],
            "properties": {
                "layout": {**_STR, "description": "The composition idea of the whole page, as a designer would brief it: grid, rhythm, how dense, where it breaks."},
                "hero": {**_STR, "description": "The first screen: which photo (or none), where the type sits, how big, what the eye hits first."},
                "signature": {**_STR, "description": "One visual device that recurs and is recognisably this business."},
                "motion": {**_STR, "description": "What moves and how, CSS only. Specific elements, not 'subtle animations'."},
            },
        },
        "hero": {
            "type": "object",
            "additionalProperties": False,
            "required": ["headline", "subline", "cta_label"],
            "properties": {
                "headline": {**_STR, "description": "Six words at most."},
                "subline": _STR,
                "cta_label": _STR,
            },
        },
        "sections": {
            "type": "array",
            "description": "Sections to build, in page order. Leave out a section when the facts cannot fill it.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "title", "purpose", "treatment", "photo"],
                "properties": {
                    "id": {"type": "string", "enum": SECTION_IDS},
                    "title": _STR,
                    "purpose": {**_STR, "description": "What this section must do for a visitor, in one sentence."},
                    "treatment": {**_STR, "description": "How this section looks: layout, scale, background. Different from the sections next to it."},
                    "photo": {**_STR, "description": "URL of the photo from FACTS.photos used here, or an empty string."},
                },
            },
        },
    },
}

SYSTEM = """You are the art director of a small studio that builds one-page websites for local businesses. The studio is known for sites that look made for one place, not filled into a template.
You receive FACTS: everything publicly known about one business, as JSON. Write the design brief for its site.

Concept
- The concept comes from what is specific to this business in FACTS (a dish, a street, a habit customers mention), not from its category.
- Poster test: the first screen alone, with the name covered, must say what kind of place this is and why this one. Brief the hero to pass it.

Design
- Commit to a direction. A page with one strong idea beats a page of safe choices.
- If FACTS.photos has photos, they carry the page: assign the strongest one to the hero and use the others where their subject fits. Each photo's `shows` tells you what is in it.
- Pick two Google Fonts with character that fit the concept. Not the pairing every site of this category uses.
- Give every section its own treatment. No two neighbours share a layout.
- Do not brief any of these: a centred hero on a pale gradient; a small uppercase label above every heading; a grid of identical rounded cards; pill buttons everywhere; a dingbat or emoji standing in for a logo.

Truth
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
