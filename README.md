# kimi-local-site-builder

From a local business's public facts to a previewable one-page site, on [Kimi K3](https://platform.kimi.ai/docs/guide/kimi-k3-quickstart). About 900 lines of Python, one dependency.

```
facts.json ──▶ brief ──▶ page ──▶ evidence gate ──▶ index.html ──▶ edits in plain words
              (JSON      (streamed)  (no model)                     (tool calls)
               schema)
```

## Why this exists

I co-founded [FlashWeb](https://flashweb.dev), where we build a website for an Italian shop or restaurant *before* they ask for one. The owner gets a preview link and pays only if they want it live. It runs in production with 10+ paying customers.

This repo is not FlashWeb's code. It is the smallest pipeline I could write that keeps the three things that product taught me, rebuilt on the Kimi API so it can be read in one sitting:

1. **Write a brief before the page.** A model asked for "a site for a pizzeria" returns the average pizzeria site. Asked first for one sentence about what is specific to *this* business, it has something to design around.
2. **The model will invent a price. Check, don't ask.** A wrong opening time on a real shop's site costs the owner customers. A prompt lowers the odds; only a check outside the model removes them.
3. **Owners change one thing at a time.** "Make the button say *Prenota*" should not regenerate the whole page, and should not cost a page's worth of output tokens.

Each lesson maps to one Kimi API feature, so the code doubles as a tour of them.

## Quickstart

```bash
git clone https://github.com/alfredoLipari/kimi-local-site-builder
cd kimi-local-site-builder
pip install -e .
export MOONSHOT_API_KEY=sk-...          # https://platform.kimi.ai

python -m sitekit build examples/forno-zagara.json
open out/index.html

python -m sitekit edit "Aggiungi un pulsante WhatsApp nell'hero"
python -m sitekit check                 # runs the gate again, no API call
```

`build` writes four files to `out/`: `brief.json`, `index.html`, `facts.json` and `report.json` (what the gate caught, and the token usage of the run).

The example business, Forno Zagara, is made up. To try your own, copy the file and change the values; the keys are free-form, the only one the code reads is `language`.

## How it works

| Step | File | Kimi feature |
|---|---|---|
| 1. Brief | [`sitekit/brief.py`](sitekit/brief.py) | Structured Output (`json_schema`, `strict`) |
| 2. Page | [`sitekit/build.py`](sitekit/build.py) | Streaming, with `reasoning_content` apart from `content` |
| 3. Evidence gate | [`sitekit/evidence.py`](sitekit/evidence.py) | None. Plain Python |
| 4. Edits | [`sitekit/edit.py`](sitekit/edit.py) | Tool calls, context cache |

Everything Kimi-specific sits in [`sitekit/kimi.py`](sitekit/kimi.py), about 150 lines around the OpenAI SDK pointed at `https://api.moonshot.ai/v1`.

### 1. A brief, as strict JSON

The first call asks for a design brief: a one-sentence concept, tone, palette, hero copy and the list of sections to build. Step 2 reads those fields directly, so the call uses Structured Output:

```python
reply = kimi.chat(
    messages,
    effort="high",
    response_format={
        "type": "json_schema",
        "json_schema": {"name": "site_brief", "strict": True, "schema": BRIEF_SCHEMA},
    },
)
brief = json.loads(reply.content)
```

The schema keeps to what strict mode handles well: nested objects, arrays, an `enum` for section ids, every field required, `additionalProperties: false`. The section list is where the brief earns its place. The model is told to plan a section only if the facts can fill it, so a business with no reviews gets no reviews section instead of an empty one.

### 2. The page, streamed

A full page is a long answer, so it is streamed. K3 always thinks before it answers, and the stream delivers the thinking in `delta.reasoning_content` and the answer in `delta.content`. Keeping them apart matters: only `content` is the page.

```python
for chunk in stream:
    if chunk.usage:                      # last chunk, choices == []
        usage.add(chunk.usage)
    for choice in chunk.choices:
        if text := getattr(choice.delta, "reasoning_content", None):
            on_delta("reasoning", text)
        if text := choice.delta.content:
            on_delta("content", text)
```

Run `build --thinking` to read the reasoning as it arrives.

The prompt fixes a small contract that the next two steps depend on:

- every block is a `<section data-section="id">`;
- colours and fonts are CSS custom properties in one `:root { }` block.

### 3. The evidence gate

No model here. The gate extracts every checkable value from the page (prices, opening times, phone numbers, emails, ratings, years, outbound links) and looks each one up in the facts file. Anything that is not there is reported with the section it sits in:

```
3/3 evidence gate
    [menu] price '€ 9,00' is not in the facts
    [about] year '1962' is not in the facts
```

The list goes back to the model as an ordinary edit request (step 4), and the gate runs again. After two rounds, whatever is left is written to `report.json` and the command exits with a non-zero status, so a pipeline can refuse to publish.

Two details worth knowing:

- **Derived links are allowed, invented ones are not.** A `tel:` or `wa.me` link must carry a phone number from the facts. A maps link built from the address is fine. An Instagram URL nobody gave us is a violation.
- **What the owner says is evidence.** If an edit request says "from June we also open for lunch, from 12:30", then 12:30 is allowed on the page from then on. Requests are kept in `out/owner-requests.jsonl` for that reason.

The gate checks values, not prose. It will not catch "the best pizza in Palermo". See [Limits](#limits).

### 4. Edits as tool calls

The model sees the whole page but answers with small tool calls:

| Tool | Does |
|---|---|
| `replace_section(section_id, html)` | swaps one section |
| `insert_section(after_section_id, html)` | adds one |
| `set_css_variables(variables)` | changes design tokens in `:root` |

```
$ python -m sitekit edit "Rendi i colori più caldi e scrivi 'Prenota' sul pulsante"
    set_css_variables
    replace_section hero
```

Each line is a tool call as it is applied; the model's one-sentence answer to the owner follows.

The output of an edit is one section, not the page. Tool errors (unknown section id, HTML that is not a single section) are returned to the model as the tool result, so it can correct itself in the next turn. The edited page goes through the gate before it is written; if the gate objects, `index.html` is left as it was.

The request is the last thing in the prompt, after the rules, the facts and the page. Consecutive edits of the same page then share a long identical prefix, which is what the API's automatic context cache needs to hit. `report.json` and the `edit` command print `cached_prompt_tokens` so you can see it.

## Notes on calling K3

Things I checked in the [API reference](https://platform.kimi.ai/docs/api/chat) while writing this, in case they save you a round trip:

- **Thinking is always on.** The dial is `reasoning_effort`: `low`, `high` or `max`, and the default is `max`. This project uses `high` for the brief and the page and `low` for edits.
- **Sampling parameters are fixed.** `temperature`, `top_p` and the penalties cannot be set on K3, so `kimi.py` never sends them.
- **Send the whole assistant message back.** In a tool loop the history needs the assistant turn with its `tool_calls` and its `reasoning_content`, not just `content`.
- **`tool_choice="required"`** makes the first turn of an edit act instead of asking a question back.
- **Use `max_completion_tokens`**, not `max_tokens`.
- **Parse `message.content` only** when you asked for JSON.
- **Ask for the usage chunk** with `stream_options={"include_usage": True}` when streaming; it arrives last, with an empty `choices`.

To run on another model, set `KIMI_MODEL` (for example `kimi-k2.6`) or pass `--model`. The K3-only parameters are left out automatically.

## Tests

```bash
python -m unittest discover -s tests -t .
```

The suite needs no key and no network. [`tests/fake_kimi.py`](tests/fake_kimi.py) is a local stand-in for the chat completions endpoint, and the tests drive the real OpenAI SDK against it through the whole pipeline: structured output, a streamed page with an invented price in it, the gate catching it, and the tool-call repair.

## Limits

- One page, one language per site. No images unless the facts list photo URLs.
- The gate is pattern-based. It covers numbers and links, the things that hurt most when wrong. It does not judge claims made in prose.
- Facts are a JSON file you write by hand. Collecting them from public sources is the other half of the real product and is out of scope here.
- No deploy step. `out/index.html` is a static file; put it wherever you host static files.

## License

MIT
