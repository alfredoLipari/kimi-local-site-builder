"""Step 2: generate the page, then loop it through the evidence gate."""

from __future__ import annotations

import json
from typing import Any, Callable

from .brief import make_brief
from .edit import edit_page
from .evidence import Violation, check
from .kimi import Kimi
from .page import extract_html

SYSTEM = """You are a senior web designer who also writes the code. You build one-page websites for local businesses that look made for one place. You receive FACTS (everything known about the business) and BRIEF (the art direction). Return the finished page. BRIEF is the direction: execute it, do not water it down.

Output
- One complete HTML document and nothing else. No explanations, no code fence.
- All CSS in one <style> in the head. No JavaScript.
- Fonts: load the two families in BRIEF.fonts with one Google Fonts <link> (plus preconnect), display=swap, only the weights you use.
- Images: only the URLs listed in FACTS.photos (you may change the w= parameter to the size you need), with alt text taken from their `shows`. No other image, icon font or external file. Inline SVG is for simple geometric marks only, never for illustrations.

Structure (later edits depend on it)
- Every block of the page is a <section data-section="ID">, using the ids and the order from BRIEF.sections.
- Design tokens are CSS custom properties in a single :root { } block (at least --background, --surface, --text, --accent, --font-display, --font-body) and the rest of the CSS uses them.

Craft
- Hero: build exactly what BRIEF.art_direction.hero describes. If it uses a photo, the photo fills the screen (object-fit: cover) with a scrim so the type stays readable. The headline is the biggest thing on the page: clamp() up to 8-10rem on desktop, tight leading, set where the brief says, which is rarely dead centre.
- Each section follows its `treatment` in BRIEF.sections. Change scale, alignment and background from one section to the next. Use full-bleed bands, asymmetric grids and generous empty space. Photos are large, never thumbnails.
- A menu or price list is typeset like a printed one: name, a leader, the price aligned right, the description beneath in a quieter voice. The signature item gets more room.
- A review is a large pull quote, not a card.
- Close with one confident band: where, when, and the phone number set big as a tel: link.
- BRIEF.art_direction.signature appears at least three times. BRIEF.art_direction.motion is implemented in CSS only (keyframes, transitions, scroll-driven animation behind @supports), and switched off under prefers-reduced-motion.
- Do not produce: a centred hero on a pale gradient, a small uppercase label above every heading, a grid of identical rounded cards, a dingbat as a logo.
- Mobile first. It must read well at 380px wide. Under 48rem, a fixed bar at the bottom of the screen carries the main action (call, or what BRIEF.hero.cta_label says).
- Real links: tel: for the phone, mailto: for the email, a maps link built from the address.

Copy
- Short and specific, in the tone of BRIEF.tone. Write each sentence once: never repeat a sentence or a paragraph in two sections.
- You may rephrase FACTS, but every fact stays exact.

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
        effort="max",
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
