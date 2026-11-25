"""Step 2: generate the page, then loop it through the evidence gate."""

from __future__ import annotations

import json
from typing import Any, Callable

from .brief import make_brief
from .edit import edit_page
from .evidence import Violation, check
from .kimi import Kimi
from .page import extract_html

SYSTEM = """You build one-page websites for local businesses. You receive FACTS (everything known about the business) and BRIEF (the design direction). Return the finished page.

Output
- One complete HTML document and nothing else. No explanations, no code fence.
- Self-contained: all CSS in one <style> in the head. No JavaScript, no external fonts, scripts or stylesheets.
- The only images are the URLs listed in FACTS.photos, if any. Otherwise design with type, colour and layout.

Structure
- Every block of the page is a <section data-section="ID">, using the ids and the order from BRIEF.sections.
- Design tokens are CSS custom properties in a single :root { } block (at least --background, --surface, --text, --accent, --font-display, --font-body) and the rest of the CSS uses them.
- Mobile first. It must read well at 380px wide and scale up.
- Real links: tel: for the phone, mailto: for the email, a maps link built from the address.

Truth
- Every price, opening time, phone number, address, rating, year and quote on the page comes from FACTS, exactly as written there.
- If FACTS does not have it, the page does not say it. Leave the block out; do not write placeholders.
- Write in the language given by FACTS.language."""


def generate_page(
    kimi: Kimi, facts: dict[str, Any], brief: dict[str, Any], on_delta: Callable[[str, str], None] | None = None
) -> str:
    reply = kimi.chat(
        [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": "FACTS:\n"
                + json.dumps(facts, ensure_ascii=False, indent=2)
                + "\n\nBRIEF:\n"
                + json.dumps(brief, ensure_ascii=False, indent=2),
            },
        ],
        effort="high",
        on_delta=on_delta or (lambda kind, text: None),  # a page is long: always stream it
    )
    return extract_html(reply.content)


def repair_request(violations: list[Violation]) -> str:
    lines = "\n".join(f"- {v}" for v in violations)
    return (
        "A check found values on the page that are not in FACTS. "
        "Fix each one: use the value from FACTS if there is one, otherwise remove the statement.\n" + lines
    )


def build(
    kimi: Kimi,
    facts: dict[str, Any],
    *,
    max_repairs: int = 2,
    on_delta: Callable[[str, str], None] | None = None,
    log: Callable[[str], None] = lambda line: None,
) -> dict[str, Any]:
    log("1/3 brief (structured output)")
    brief = make_brief(kimi, facts)
    log(f"    concept: {brief['concept']}")

    log("2/3 page (streaming)")
    html = generate_page(kimi, facts, brief, on_delta)

    log("3/3 evidence gate")
    violations = check(html, facts)
    rounds = []
    for _ in range(max_repairs):
        if not violations:
            break
        for v in violations:
            log(f"    {v}")
        rounds.append([str(v) for v in violations])
        html, _ = edit_page(kimi, html, facts, repair_request(violations))
        violations = check(html, facts)
    log("    clean" if not violations else f"    {len(violations)} unresolved, see report.json")
    return {
        "brief": brief,
        "html": html,
        "repairs": rounds,
        "violations": [str(v) for v in violations],
        "usage": kimi.usage.as_dict(),
    }
