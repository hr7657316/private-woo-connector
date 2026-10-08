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

from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset, StdioTransport
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")  # provider API keys can live next to the WOO_* settings (git-ignored)
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

DEFAULT_MODEL = "groq:openai/gpt-oss-120b"
DEFAULT_QUESTION = "Which orders are on hold, and what is their combined total?"

INSTRUCTIONS = """\
You are an operations analyst for a WooCommerce store. Answer only from the tools - never invent
order numbers, totals or stock counts. Quote order numbers (#1234) and SKUs. Money is in the store
currency returned by the tools. When a list is paginated (has_more=true), fetch further pages
before summarising. Be concise."""


def main() -> None:
    model = os.environ.get("MODEL", DEFAULT_MODEL)
    question = " ".join(sys.argv[1:]).strip() or DEFAULT_QUESTION

    toolset = MCPToolset(
        StdioTransport("uv", ["run", "woo-mcp"], cwd=str(ROOT)),
        include_instructions=True,  # the server's own usage notes reach the model too
    )
    agent = Agent(model, instructions=INSTRUCTIONS, toolsets=[toolset])

    print(f"model     {model}\nquestion  {question}\n")
    result = asyncio.run(_run(agent, question))

    for message in result.all_messages():
        if isinstance(message, ModelResponse):
            for part in message.parts:
                if isinstance(part, ToolCallPart):
                    print(f"→ {part.tool_name}({json.dumps(part.args_as_dict(), ensure_ascii=False)})")
        elif isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    print(f"← {part.tool_name}: {_brief(part.content)}")

    answer = "".join(p.content for p in result.response.parts if isinstance(p, TextPart)).strip()
    print(f"\nanswer\n{answer}\n")
    usage = result.usage
    print(f"usage     {usage.requests} model request(s), {usage.input_tokens} in / {usage.output_tokens} out tokens")


async def _run(agent: Agent, question: str):
    async with agent:  # starts the MCP subprocess; stopped on exit
        return await agent.run(question)


def _brief(content: object, limit: int = 160) -> str:
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + f"… ({len(text)} chars)"


if __name__ == "__main__":
    main()
