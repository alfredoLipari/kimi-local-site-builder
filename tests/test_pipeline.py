"""Drive the whole pipeline through the real OpenAI SDK against a local fake."""

import json
import unittest
from pathlib import Path

from openai import OpenAI

from sitekit.build import build
from sitekit.edit import edit_page
from sitekit.evidence import check
from sitekit.kimi import Kimi
from tests.fake_kimi import PAGE, FakeKimi

FACTS = json.loads((Path(__file__).parent.parent / "examples" / "forno-zagara.json").read_text(encoding="utf-8"))


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.fake = FakeKimi()
        self.kimi = Kimi(client=OpenAI(api_key="test", base_url=self.fake.base_url, max_retries=0), model="kimi-k3")

    def tearDown(self):
        self.fake.close()

    def test_build_generates_gates_and_repairs(self):
        seen = {"reasoning": "", "content": ""}

        def on_delta(kind, text):
            seen[kind] += text

        result = build(self.kimi, FACTS, on_delta=on_delta)

        # the streamed page had an invented pizza price and founding year; the gate caught both
        self.assertEqual(len(result["repairs"]), 1)
        self.assertEqual(len(result["repairs"][0]), 2)
        self.assertEqual(result["violations"], [])
        self.assertNotIn("Diavola", result["html"])
        self.assertIn("Zagara € 12,50", result["html"])
        self.assertEqual(seen["reasoning"], "Thinking about the layout. Menu first.")
        self.assertTrue(seen["content"].startswith("```html"))
        self.assertTrue(result["html"].startswith("<!doctype html>"))

        brief_req, page_req, repair_req, closing_req = self.fake.requests
        # K3: reasoning_effort is sent, sampling parameters never are
        for req in self.fake.requests:
            self.assertEqual(req["model"], "kimi-k3")
            self.assertIn(req["reasoning_effort"], ("low", "high", "max"))
            self.assertFalse({"temperature", "top_p", "max_tokens"} & req.keys())
        self.assertEqual(brief_req["response_format"]["type"], "json_schema")
        self.assertTrue(brief_req["response_format"]["json_schema"]["strict"])
        self.assertTrue(page_req["stream"])
        self.assertEqual(page_req["stream_options"], {"include_usage": True})
        self.assertEqual(repair_req["tool_choice"], "required")
        self.assertNotIn("tool_choice", closing_req)

        # the assistant turn goes back complete: tool calls and reasoning_content
        assistant, tool = closing_req["messages"][-2:]
        self.assertEqual(assistant["role"], "assistant")
        self.assertEqual(assistant["reasoning_content"], "The menu has two invented values.")
        self.assertEqual(assistant["tool_calls"][0]["function"]["name"], "replace_section")
        self.assertEqual(tool, {"role": "tool", "tool_call_id": "replace_section_0",
                                "content": json.dumps({"ok": True, "sections": ["hero", "menu", "contact"]})})

        self.assertEqual(result["usage"], {"calls": 4, "prompt_tokens": 4000, "cached_prompt_tokens": 3200,
                                           "completion_tokens": 800, "reasoning_tokens": 200})

    def test_edit_returns_page_and_answer(self):
        html, answer = edit_page(self.kimi, PAGE, FACTS, "Correggi il menu")
        self.assertEqual(answer, "Fatto: ho corretto il menu.")
        self.assertEqual(check(html, FACTS), [])
        first = self.fake.requests[0]
        self.assertEqual([t["function"]["name"] for t in first["tools"]],
                         ["replace_section", "insert_section", "set_css_variables"])
        self.assertTrue(first["messages"][1]["content"].endswith("REQUEST:\nCorreggi il menu"))

    def test_other_models_get_no_k3_only_parameters(self):
        kimi = Kimi(client=self.kimi.client, model="kimi-k2.6")
        edit_page(kimi, PAGE, FACTS, "Correggi il menu")
        for req in self.fake.requests:
            self.assertNotIn("reasoning_effort", req)
            self.assertNotIn("tool_choice", req)


if __name__ == "__main__":
    unittest.main()
