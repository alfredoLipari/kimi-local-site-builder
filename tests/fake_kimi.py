"""A local stand-in for the Kimi chat completions endpoint.

It speaks just enough of the protocol for the tests to drive the real OpenAI
SDK through the whole pipeline without a key or a network: structured output,
a streamed answer with reasoning_content, and a tool-call round trip.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BRIEF = {
    "concept": "La pizzeria di via dei Candelai dove l'arancia finisce sulla pizza.",
    "tone": "Diretto, di quartiere",
    "palette": {"background": "#fbf6ee", "surface": "#ffffff", "text": "#1d1a16", "accent": "#d9622b"},
    "fonts": {"display": "Fraunces", "body": "Instrument Sans", "why": "Un serif morbido per un forno di quartiere."},
    "art_direction": {
        "layout": "Una colonna stretta che si apre in fasce a tutta larghezza.",
        "hero": "La foto della brace a tutto schermo, il nome in basso a sinistra.",
        "signature": "Un cerchio arancione, come una scorza.",
        "motion": "Il cerchio ruota lentamente.",
    },
    "hero": {"headline": "Forno Zagara", "subline": "Impasto di 48 ore, forno a legna.", "cta_label": "Chiama per prenotare"},
    "sections": [
        {"id": "hero", "title": "Forno Zagara", "purpose": "Dire chi siamo.", "treatment": "Foto a tutto schermo.", "photo": ""},
        {"id": "menu", "title": "Le pizze", "purpose": "Mostrare le pizze e i prezzi.", "treatment": "Carta stampata.", "photo": ""},
        {"id": "contact", "title": "Dove siamo", "purpose": "Far chiamare.", "treatment": "Fascia scura.", "photo": ""},
    ],
}

MENU_BAD = '<section data-section="menu"><h2>Le pizze</h2><p>Dal 1962.</p><ul><li>Margherita € 8,00</li><li>Diavola € 9,00</li></ul></section>'
MENU_GOOD = '<section data-section="menu"><h2>Le pizze</h2><ul><li>Margherita € 8,00</li><li>Zagara € 12,50</li></ul></section>'

PAGE = f"""<!doctype html>
<html lang="it"><head><meta charset="utf-8"><title>Forno Zagara</title>
<style>
:root {{
  --background: #fbf6ee;
  --accent: #d9622b;
}}
body {{ background: var(--background); }}
</style></head><body>
<section data-section="hero"><h1>Forno Zagara</h1><a href="tel:+390915550142">Chiama per prenotare</a></section>
{MENU_BAD}
<section data-section="contact"><p>Via dei Candelai 48, 90134 Palermo · 19:00 – 23:30</p></section>
<footer>© 2026 Forno Zagara</footer>
</body></html>"""

USAGE = {
    "prompt_tokens": 1000,
    "completion_tokens": 200,
    "total_tokens": 1200,
    "completion_tokens_details": {"reasoning_tokens": 50},
    "prompt_tokens_details": {"cached_tokens": 800, "cache_write_tokens": 0},
}


def _completion(message: dict, finish: str = "stop") -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "kimi-k3",
        "choices": [{"index": 0, "message": {"role": "assistant", **message}, "finish_reason": finish}],
        "usage": USAGE,
    }


class FakeKimi:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(body)
                if body.get("stream"):
                    self._stream(body)
                else:
                    self._json(fake.answer(body))

            def _json(self, payload: dict) -> None:
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _stream(self, body: dict) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()

                def send(delta: dict, finish=None) -> None:
                    chunk = {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "kimi-k3",
                             "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())

                send({"role": "assistant", "reasoning_content": "Thinking about the layout. "})
                send({"reasoning_content": "Menu first."})
                half = len(PAGE) // 2
                send({"content": "```html\n" + PAGE[:half]})
                send({"content": PAGE[half:] + "\n```"})
                send({}, "stop")
                if body.get("stream_options", {}).get("include_usage"):
                    usage = {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "kimi-k3", "choices": [], "usage": USAGE}
                    self.wfile.write(f"data: {json.dumps(usage)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def answer(self, body: dict) -> dict:
        if body.get("response_format"):
            return _completion({"content": json.dumps(BRIEF), "reasoning_content": "Reading the facts."})
        if body.get("tools"):
            if body["messages"][-1]["role"] == "tool":
                return _completion({"content": "Fatto: ho corretto il menu."})
            call = {"id": "replace_section_0", "type": "function",
                    "function": {"name": "replace_section", "arguments": json.dumps({"section_id": "menu", "html": MENU_GOOD})}}
            return _completion({"content": "", "reasoning_content": "The menu has two invented values.", "tool_calls": [call]}, "tool_calls")
        return _completion({"content": "ok"})

    def close(self) -> None:
        self.server.shutdown()
