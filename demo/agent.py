"""Run any LLM against the WooCommerce MCP server - the provider is just an env var.

    MODEL=groq:openai/gpt-oss-120b     GROQ_API_KEY=...       uv run --extra demo demo/agent.py "which orders are on hold?"
    MODEL=anthropic:claude-opus-5      ANTHROPIC_API_KEY=...  uv run --extra demo demo/agent.py "..."
    MODEL=openai:gpt-6.1-sol           OPENAI_API_KEY=...     uv run --extra demo demo/agent.py "..."
    MODEL=google:gemini-3.8-flash      GOOGLE_API_KEY=...     uv run --extra demo demo/agent.py "..."

Model IDs verified 2026-10-08; see README "Ask an LLM" for the per-vendor catalogue links.
API keys may also be placed in the repo's .env (git-ignored) instead of the shell.

The script launches `woo-mcp` over stdio exactly like Claude Desktop / Codex / Gemini CLI would,
hands its tools to the model via pydantic-ai, and prints every tool call so the transcript shows
the agent's reasoning path, not just its answer. Nothing here is specific to one vendor.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runner import DEFAULT_MODEL, ask  # noqa: E402

DEFAULT_QUESTION = "Which orders are on hold, and what is their combined total?"


def main() -> None:
    model = os.environ.get("MODEL", DEFAULT_MODEL)
    question = " ".join(sys.argv[1:]).strip() or DEFAULT_QUESTION
    print(f"model     {model}\nquestion  {question}\n")

    run = asyncio.run(ask(model, question))
    if run.error:
        sys.exit(f"failed after {run.seconds:.1f}s: {run.error}")

    for call in run.tool_calls:
        print(f"→ {call.name}({json.dumps(call.args, ensure_ascii=False)})")
        print(f"← {call.name}: {call.result_preview}")
    print(f"\nanswer\n{run.answer}\n")
    print(f"usage     {run.requests} model request(s), {run.input_tokens} in / {run.output_tokens} out tokens, {run.seconds:.1f}s")


if __name__ == "__main__":
    main()
