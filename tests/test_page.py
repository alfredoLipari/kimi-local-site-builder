import unittest

from sitekit import page

HTML = """<html><head><style>
:root {
  --accent: #d9622b;
  --text: #111;
}
</style></head><body>
<section data-section="hero"><h1>Ciao</h1></section>
<section data-section="menu" class="m">
  <section class="inner"><p>nested</p></section>
</section>
</body></html>"""


class Page(unittest.TestCase):
    def test_sections_in_order_with_nesting(self):
        spans = page.sections(HTML)
        self.assertEqual(list(spans), ["hero", "menu"])
        a, b = spans["menu"]
        self.assertTrue(HTML[a:b].startswith('<section data-section="menu"'))
        self.assertTrue(HTML[a:b].rstrip().endswith("</section>"))
        self.assertIn("nested", HTML[a:b])

    def test_replace_section(self):
        out = page.replace_section(HTML, "hero", '<section data-section="hero"><h1>Buonasera</h1></section>')
        self.assertIn("Buonasera", out)
        self.assertNotIn("Ciao", out)
        self.assertEqual(list(page.sections(out)), ["hero", "menu"])

    def test_replace_rejects_wrong_id_and_unknown_section(self):
        with self.assertRaises(ValueError):
            page.replace_section(HTML, "hero", '<section data-section="other"></section>')
        with self.assertRaises(KeyError):
            page.replace_section(HTML, "nope", '<section data-section="nope"></section>')

    def test_insert_section(self):
        out = page.insert_section(HTML, "hero", '<section data-section="hours"><p>x</p></section>')
        self.assertEqual(list(page.sections(out)), ["hero", "hours", "menu"])
        with self.assertRaises(ValueError):
            page.insert_section(out, "hero", '<section data-section="hours"></section>')

    def test_css_variables(self):
        out = page.set_css_variables(HTML, {"--accent": "#b03a2e", "--radius": "12px"})
        self.assertEqual(page.css_variables(out), {"--accent": "#b03a2e", "--text": "#111", "--radius": "12px"})
        with self.assertRaises(ValueError):
            page.set_css_variables(HTML, {"--accent": "red; } body { display:none"})

    def test_extract_html(self):
        self.assertTrue(page.extract_html("Here you go:\n```html\n<!doctype html><html></html>\n```").startswith("<!doctype html>"))
        with self.assertRaises(ValueError):
            page.extract_html("Sorry, I cannot.")


if __name__ == "__main__":
    unittest.main()
