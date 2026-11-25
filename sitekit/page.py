"""Helpers for the generated page: locate sections, swap them, edit CSS variables.

The builder is asked to wrap every block in <section data-section="id"> and to
keep its design tokens as CSS custom properties in :root. That contract is what
lets a later edit touch one piece of the page instead of regenerating all of it.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser


class _SectionFinder(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=False)
        self._starts = [0]
        for line in html.splitlines(keepends=True):
            self._starts.append(self._starts[-1] + len(line))
        self._stack: list[tuple[str | None, int]] = []
        self.spans: dict[str, tuple[int, int]] = {}
        self._html = html
        self.feed(html)
        self.close()

    def _offset(self) -> int:
        line, col = self.getpos()
        return self._starts[line - 1] + col

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "section":
            self._stack.append((dict(attrs).get("data-section"), self._offset()))

    def handle_endtag(self, tag: str) -> None:
        if tag == "section" and self._stack:
            name, start = self._stack.pop()
            end = self._html.index(">", self._offset()) + 1
            if name and name not in self.spans:
                self.spans[name] = (start, end)


def sections(html: str) -> dict[str, tuple[int, int]]:
    """Map each data-section id to its (start, end) offsets, in page order."""
    spans = _SectionFinder(html).spans
    return dict(sorted(spans.items(), key=lambda kv: kv[1][0]))


def replace_section(html: str, section_id: str, new_html: str) -> str:
    spans = sections(html)
    if section_id not in spans:
        raise KeyError(f"no section '{section_id}'; the page has: {', '.join(spans) or 'none'}")
    _require_section(new_html, section_id)
    start, end = spans[section_id]
    return html[:start] + new_html.strip() + html[end:]


def insert_section(html: str, after_section_id: str, new_html: str) -> str:
    spans = sections(html)
    if after_section_id not in spans:
        raise KeyError(f"no section '{after_section_id}'; the page has: {', '.join(spans) or 'none'}")
    new_ids = list(sections(new_html))
    if len(new_ids) != 1:
        raise ValueError('html must be exactly one <section data-section="..."> element')
    if new_ids[0] in spans:
        raise ValueError(f"section '{new_ids[0]}' already exists; use replace_section")
    end = spans[after_section_id][1]
    return html[:end] + "\n" + new_html.strip() + html[end:]


def set_css_variables(html: str, variables: dict[str, str]) -> str:
    """Update (or add) custom properties in the first :root { } block."""
    match = re.search(r":root\s*\{([^}]*)\}", html)
    if not match:
        raise ValueError("the page has no :root { } block")
    body = match.group(1)
    for name, value in variables.items():
        if not re.fullmatch(r"--[A-Za-z0-9_-]+", name):
            raise ValueError(f"'{name}' is not a CSS custom property name")
        if re.search(r"[;{}<>]", value):
            raise ValueError(f"invalid value for {name}")
        pattern = re.compile(rf"({re.escape(name)}\s*:\s*)[^;]*;")
        if pattern.search(body):
            body = pattern.sub(lambda m: f"{m.group(1)}{value};", body, count=1)
        else:
            body = body.rstrip() + f"\n  {name}: {value};\n"
    return html[: match.start(1)] + body + html[match.end(1) :]


def css_variables(html: str) -> dict[str, str]:
    match = re.search(r":root\s*\{([^}]*)\}", html)
    if not match:
        return {}
    return {n: v.strip() for n, v in re.findall(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;]+);", match.group(1))}


def _require_section(new_html: str, section_id: str) -> None:
    ids = list(sections(new_html))
    if ids != [section_id]:
        raise ValueError(f'html must be exactly one <section data-section="{section_id}"> element')


def extract_html(text: str) -> str:
    """Return the HTML document from a model answer, with or without a code fence."""
    fenced = re.search(r"```(?:html)?\s*\n(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start = text.lower().find("<!doctype")
    if start == -1:
        start = text.lower().find("<html")
    if start == -1:
        raise ValueError("the model did not return an HTML document")
    return text[start:].strip() + "\n"
