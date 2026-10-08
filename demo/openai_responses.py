"""Ask an OpenAI model a question through the hosted MCP endpoint, using the OpenAI Responses API's
native remote-MCP support (no pydantic-ai, no local server - OpenAI's servers call the endpoint).

    OPENAI_API_KEY=sk-…  MCP_URL=https://…/mcp  WOO_MCP_TOKEN=…  uv run --extra demo demo/openai_responses.py "Which orders are on hold?"

Requires the `openai` package (`uv add --optional demo openai`). Model id verified 2026-10-08 against
https://developers.openai.com/api/docs/models.
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
MODEL = os.environ.get("OPENAI_MODEL", "gpt-6.1-sol")


def main() -> None:
    question = " ".join(sys.argv[1:]).strip() or "Which orders are on hold, and what is their combined total?"
    url = os.environ["MCP_URL"]
    token = os.environ["WOO_MCP_TOKEN"]

    client = OpenAI()
    response = client.responses.create(
        model=MODEL,
        input=question,
        instructions="You are an operations analyst for a WooCommerce store. Answer only from the tools; quote order numbers and SKUs.",
        tools=[
            {
                "type": "mcp",
                "server_label": "woocommerce",
                "server_url": url,
                "headers": {"Authorization": f"Bearer {token}"},
                "require_approval": "never",  # every tool is read-only
            }
        ],
    )
    for item in response.output:
        if item.type == "mcp_call":
            print(f"→ {item.name}({item.arguments})")
    print(f"\nanswer\n{response.output_text}")


if __name__ == "__main__":
    main()
