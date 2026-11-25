"""Command line: python -m sitekit build|edit|check"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import build
from .edit import edit_page
from .evidence import check
from .kimi import Kimi


def _progress(show_thinking: bool):
    counts = {"reasoning": 0, "content": 0}

    def on_delta(kind: str, text: str) -> None:
        counts[kind] += len(text)
        if show_thinking and kind == "reasoning":
            sys.stderr.write(text)
        else:
            sys.stderr.write(f"\r    thinking {counts['reasoning']:>6} chars | page {counts['content']:>6} chars")
        sys.stderr.flush()

    return on_delta


def _statements(out: Path) -> list[str]:
    path = out / "owner-requests.jsonl"
    if not path.exists():
        return []
    return [json.loads(line)["request"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def cmd_build(args: argparse.Namespace) -> int:
    facts = json.loads(Path(args.facts).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    kimi = Kimi(model=args.model)
    result = build(kimi, facts, on_delta=_progress(args.thinking), log=lambda line: print("\n" + line if line[0].isdigit() else line, file=sys.stderr))
    (out / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "brief.json").write_text(json.dumps(result["brief"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "index.html").write_text(result["html"], encoding="utf-8")
    report = {k: result[k] for k in ("repairs", "violations", "usage")} | {"model": kimi.model}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{out / 'index.html'}  ({json.dumps(result['usage'])})")
    return 1 if result["violations"] else 0


def cmd_edit(args: argparse.Namespace) -> int:
    out = Path(args.out)
    facts = json.loads((out / "facts.json").read_text(encoding="utf-8"))
    html = (out / "index.html").read_text(encoding="utf-8")
    kimi = Kimi(model=args.model)

    def on_tool(name: str, tool_args: dict, error: str | None) -> None:
        target = tool_args.get("section_id") or tool_args.get("after_section_id") or ""
        print(f"    {name} {target}".rstrip() + (f"  -> rejected: {error}" if error else ""), file=sys.stderr)

    new_html, answer = edit_page(kimi, html, facts, args.request, on_tool=on_tool)
    # What the owner says counts as evidence from now on ("our new number is ...").
    statements = _statements(out) + [args.request]
    violations = check(new_html, facts, statements)
    if violations:
        for v in violations:
            print(f"    {v}", file=sys.stderr)
        print("Edit rejected by the evidence gate; index.html left unchanged.", file=sys.stderr)
        return 1
    (out / "index.html").write_text(new_html, encoding="utf-8")
    with (out / "owner-requests.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"request": args.request}, ensure_ascii=False) + "\n")
    print(answer or "Done.")
    print(json.dumps(kimi.usage.as_dict()), file=sys.stderr)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    out = Path(args.out)
    facts = json.loads((out / "facts.json").read_text(encoding="utf-8"))
    violations = check((out / "index.html").read_text(encoding="utf-8"), facts, _statements(out))
    for v in violations:
        print(v)
    print("clean" if not violations else f"{len(violations)} problem(s)")
    return 1 if violations else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sitekit", description="Build and edit a local-business site with Kimi.")
    parser.add_argument("--model", default=None, help="Kimi model id (default: $KIMI_MODEL or kimi-k3)")
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="facts.json -> brief, page, report")
    b.add_argument("facts", help="path to a facts file, see examples/")
    b.add_argument("-o", "--out", default="out", help="output folder (default: out)")
    b.add_argument("--thinking", action="store_true", help="print the model's reasoning while it streams")
    b.set_defaults(func=cmd_build)

    e = sub.add_parser("edit", help="change the built page with a plain-language request")
    e.add_argument("request", help='e.g. "Add a WhatsApp button to the hero"')
    e.add_argument("-o", "--out", default="out")
    e.set_defaults(func=cmd_edit)

    c = sub.add_parser("check", help="run the evidence gate on the built page (no API call)")
    c.add_argument("-o", "--out", default="out")
    c.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
