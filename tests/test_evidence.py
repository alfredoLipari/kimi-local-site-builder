import json
import unittest
from pathlib import Path

from sitekit.evidence import check

FACTS = json.loads((Path(__file__).parent.parent / "examples" / "forno-zagara.json").read_text(encoding="utf-8"))


def page(body: str) -> str:
    return f"<!doctype html><html><body>{body}</body></html>"


def kinds(html: str, statements=()) -> list[tuple[str, str]]:
    return [(v.kind, v.section) for v in check(html, FACTS, statements)]


class EvidenceGate(unittest.TestCase):
    def test_true_page_is_clean(self):
        html = page(
            '<section data-section="menu">Margherita € 8,00 · Zagara 12,50 € · Sfincione 6.50€</section>'
            '<section data-section="contact">Martedì – Domenica 19:00–23:30 · <a href="tel:+390915550142">091 555 0142</a>'
            ' · <a href="mailto:ciao@fornozagara.example">ciao@fornozagara.example</a>'
            ' · <a href="https://www.google.com/maps/search/?api=1&query=Via+dei+Candelai+48+Palermo">Mappa</a>'
            ' · 4,7/5 su Google</section><footer>© 2026 Forno Zagara</footer>'
        )
        self.assertEqual(check(html, FACTS), [])

    def test_invented_price(self):
        self.assertEqual(kinds(page('<section data-section="menu">Diavola € 9,00</section>')), [("price", "menu")])

    def test_invented_opening_time(self):
        self.assertEqual(kinds(page('<section data-section="hours">Aperti dalle 12:30</section>')), [("time", "hours")])

    def test_invented_phone_and_whatsapp(self):
        html = page('<section data-section="contact"><a href="https://wa.me/393331234567">WhatsApp</a> 333 123 4567</section>')
        self.assertEqual(sorted(kinds(html)), [("WhatsApp link", "contact"), ("phone", "contact")])

    def test_whatsapp_link_to_the_known_number_is_fine(self):
        self.assertEqual(kinds(page('<section data-section="contact"><a href="https://wa.me/390915550142">WhatsApp</a></section>')), [])

    def test_invented_year_and_rating(self):
        html = page('<section data-section="about">A Palermo dal 1962. 4,9/5 su Google.</section>')
        self.assertEqual(sorted(kinds(html)), [("rating", "about"), ("year", "about")])

    def test_unknown_link(self):
        html = page('<section data-section="contact"><a href="https://instagram.com/fornozagara">Instagram</a></section>')
        self.assertEqual(kinds(html), [("link", "contact")])

    def test_value_outside_any_section_is_reported_on_the_page(self):
        self.assertEqual(kinds(page("<header>Menu da € 5</header>")), [("price", "page")])

    def test_owner_statement_becomes_evidence(self):
        html = page('<section data-section="hours">Da giugno aperti anche a pranzo dalle 12:30</section>')
        self.assertEqual(kinds(html, ["Da giugno apriamo anche a pranzo, dalle 12:30 alle 15:00"]), [])

    def test_styles_and_scripts_are_ignored(self):
        self.assertEqual(kinds("<html><head><style>.a{margin:12.30px;width:1962px}</style></head><body></body></html>"), [])


if __name__ == "__main__":
    unittest.main()
