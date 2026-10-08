"""Write the MCP tool specification (names, descriptions, JSON input/output schemas) to tool_spec.json.

Run:  uv run scripts/export_tool_spec.py
The output is what any MCP host receives from `tools/list`; committed so reviewers can read the
contract without starting the server.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from woo_connector.mcp_server import server

OUT = Path(__file__).resolve().parent.parent / "tool_spec.json"


async def export() -> list[dict]:
    tools = await server.list_tools()
    return [t.model_dump(by_alias=True, exclude_none=True, mode="json") for t in tools]


def main() -> None:
    spec = {
        "server": server.name,
        "instructions": server.instructions,
        "tools": asyncio.run(export()),
    }
    OUT.write_text(json.dumps(spec, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT} ({len(spec['tools'])} tools)")


if __name__ == "__main__":
    main()
