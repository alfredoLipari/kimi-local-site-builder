"""Step 3: the evidence gate. No model involved.

A generated site for a real shop must not state a price, a phone number, an
opening time, a rating or a founding year that nobody gave us. Asking the model
nicely is not enough, so every checkable value on the page is extracted and
looked up in the evidence: the facts file plus anything the owner said.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

from .page import sections

MONEY = re.compile(r"(?:€|EUR|eur)\s?(\d{1,4}(?:[.,]\d{1,2})?)|(\d{1,4}(?:[.,]\d{1,2})?)\s?(?:€|euro\b|EUR\b)", re.I)
TIME = re.compile(r"(?<![\d.,:])([01]?\d|2[0-3])[:.]([0-5]\d)(?![\d:])")
PHONE = re.compile(r"(?<![\w.])\+?\d[\d\s().\-/]{6,}\d")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RATING = re.compile(r"(?<![\d.,])([1-5][.,]\d)\s?(?:/\s?5|su\s?5|stelle|stars|★)", re.I)
YEAR = re.compile(r"(?<![\d.,/:\-©])\b(1[89]\d\d|20\d\d)\b(?![\d/:\-]|[.,]\d)")
COPYRIGHT_YEAR = re.compile(r"(?:©|&copy;|\(c\)|copyright)\s*(?:\d{4}\s*[-–]\s*)?\d{4}", re.I)

# Links a page may build from facts it already has, without them being facts themselves.
DERIVED_HOSTS = {"wa.me", "api.whatsapp.com", "maps.google.com", "www.google.com", "maps.apple.com", "www.openstreetmap.org"}
# Web fonts are presentation, not a statement about the business.
FONT_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}
CSS_URL = re.compile(r"url\(\s*['\"]?([^'\")\s]+)['\"]?\s*\)")


@dataclass(frozen=True)
class Violation:
    kind: str
    value: str
    section: str

    def __str__(self) -> str:
        return f"[{self.section}] {self.kind} '{self.value}' is not in the facts"


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.links: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        for name, value in attrs:
            if name in ("href", "src", "poster") and value:
                self.links.append(value)
            elif name == "srcset" and value:
                self.links += [part.split()[0] for part in value.split(",") if part.strip()]
            elif name == "style" and value:
                self.links += CSS_URL.findall(value)
            elif name in ("alt", "title", "aria-label", "content") and value:
                self.text.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            self.links += CSS_URL.findall(data)  # background images count as images
        else:
            self.text.append(data)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _money(value: str) -> str:
    return f"{float(value.replace(',', '.')):.2f}"


def _claims(text: str) -> set[tuple[str, str, str]]:
    """(kind, normalised value, value as written) for everything checkable in a text."""
    found: set[tuple[str, str, str]] = set()
    text = COPYRIGHT_YEAR.sub(" ", text)
    for m in EMAIL.finditer(text):
        found.add(("email", m.group().lower(), m.group()))
    text = EMAIL.sub(" ", text)
    for m in MONEY.finditer(text):
        found.add(("price", _money(m.group(1) or m.group(2)), m.group().strip()))
    text = MONEY.sub(" ", text)
    for m in RATING.finditer(text):
        found.add(("rating", m.group(1).replace(",", "."), m.group().strip()))
    text = RATING.sub(" ", text)
    for m in PHONE.finditer(text):
        if len(_digits(m.group())) >= 8:
            found.add(("phone", _digits(m.group()), m.group().strip()))
    text = PHONE.sub(lambda m: " " if len(_digits(m.group())) >= 8 else m.group(), text)
    for m in TIME.finditer(text):
        found.add(("time", f"{int(m.group(1)):02d}:{m.group(2)}", m.group()))
    text = TIME.sub(" ", text)
    for m in YEAR.finditer(text):
        found.add(("year", m.group(1), m.group(1)))
    return found


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for k, v in value.items():
            if not str(k).startswith("_"):
                yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float)):
        yield str(value)
    else:
        yield str(value)


class Evidence:
    """Everything we are allowed to state: the facts, plus what the owner told us."""

    def __init__(self, facts: dict[str, Any], statements: Iterable[str] = ()) -> None:
        strings = list(_strings(facts)) + list(statements)
        self.text = "\n".join(strings)
        claims = _claims(self.text)
        self.values = {(kind, norm) for kind, norm, _ in claims}
        self.phones = {norm for kind, norm, _ in claims if kind == "phone"}
        # A bare number in the facts ("price": 8.5, "rating": 4.7) backs a price or a rating.
        self.numbers = set()
        for s in strings:
            if re.fullmatch(r"\d+(?:[.,]\d+)?", s.strip()):
                self.numbers.add(float(s.strip().replace(",", ".")))
        photos = facts.get("photos") or []
        self.photos = [p["url"] if isinstance(p, dict) else str(p) for p in photos]
        self.photo_hosts = {urlparse(u).netloc.lower() for u in self.photos}
        self.hosts = {h.lower() for h in re.findall(r"https?://([^/\s\"']+)", self.text)}
        self.hosts |= {h.lower() for h in re.findall(r"\b((?:[\w-]+\.)+[a-z]{2,})\b", self.text)}

    def supports(self, kind: str, norm: str) -> bool:
        if (kind, norm) in self.values:
            return True
        if kind in ("price", "rating"):
            return float(norm) in self.numbers
        if kind == "phone":
            # +39 091 555 0142 and 091 555 0142 are the same number
            return any(norm.endswith(p[-8:]) and (norm.endswith(p) or p.endswith(norm)) for p in self.phones)
        return False

    def supports_link(self, link: str) -> str | None:
        """Return None if the link is fine, otherwise a (kind, value) description."""
        link = link.strip()
        if not link or link.startswith(("#", "/", "data:")):
            return None
        if link.startswith("tel:"):
            return None if self.supports("phone", _digits(link)) else f"phone link|{link}"
        if link.startswith("mailto:"):
            address = unquote(link[7:].split("?")[0]).lower()
            return None if ("email", address) in self.values else f"email link|{link}"
        url = urlparse(link)
        if url.scheme not in ("http", "https"):
            return None
        host = url.netloc.lower()
        if host in ("wa.me", "api.whatsapp.com"):
            number = _digits(url.path) or _digits(url.query)
            return None if self.supports("phone", number) else f"WhatsApp link|{link}"
        if host in DERIVED_HOSTS or host in FONT_HOSTS:
            return None
        if host in self.photo_hosts:
            # an image host is only as good as the exact photo: the path must be one we were given
            return None if any(url.path == urlparse(u).path for u in self.photos) else f"image|{link}"
        if host in self.hosts or host.removeprefix("www.") in self.hosts:
            return None
        return f"link|{link}"


def check(html: str, facts: dict[str, Any], statements: Iterable[str] = ()) -> list[Violation]:
    evidence = Evidence(facts, statements)
    spans = sections(html)
    parts = [(name, html[a:b]) for name, (a, b) in spans.items()]
    outside, cursor = [], 0
    for a, b in spans.values():
        outside.append(html[cursor:a])
        cursor = max(cursor, b)
    outside.append(html[cursor:])
    parts.append(("page", "".join(outside)))

    violations: list[Violation] = []
    for name, fragment in parts:
        parser = _Text()
        parser.feed(fragment)
        for kind, norm, written in sorted(_claims(" ".join(parser.text))):
            if not evidence.supports(kind, norm):
                violations.append(Violation(kind, written, name))
        for link in parser.links:
            problem = evidence.supports_link(link)
            if problem:
                kind, value = problem.split("|", 1)
                violations.append(Violation(kind, value, name))
    return list(dict.fromkeys(violations))


def to_json(violations: list[Violation]) -> str:
    return json.dumps([asdict(v) for v in violations], ensure_ascii=False, indent=2)
