# Using the hosted endpoint (no Docker, no clone)

Endpoint: `https://woo-mcp-production-1b5f.up.railway.app/mcp` — send `Authorization: Bearer <token>` (token shared out-of-band).

**Hosts that accept a remote MCP URL + headers** (Cursor, Codex CLI `mcp_servers.*.url`, Claude Code `claude mcp add --transport http`):

```bash
claude mcp add --transport http woocommerce https://woo-mcp-production-1b5f.up.railway.app/mcp \
  --header "Authorization: Bearer <token>"
```

```json
{ "mcpServers": { "woocommerce": {
    "url": "https://woo-mcp-production-1b5f.up.railway.app/mcp",
    "headers": { "Authorization": "Bearer <token>" } } } }
```

**stdio-only hosts** (Claude Desktop) bridge with `mcp-remote`:

```json
{ "mcpServers": { "woocommerce": {
    "command": "npx",
    "args": ["-y", "mcp-remote", "https://woo-mcp-production-1b5f.up.railway.app/mcp",
             "--header", "Authorization: Bearer <token>"] } } }
```

**ChatGPT (chatgpt.com, Plus/Pro/Team)** — its connectors cannot send custom headers (OAuth or none), so pass the
token in the URL (the server must run with `WOO_MCP_ALLOW_QUERY_TOKEN=1`; the hosted demo does, and scrubs the token from its access log). *Settings → Connectors → Advanced → Developer mode → Create*: name `WooCommerce`, URL
`https://woo-mcp-production-1b5f.up.railway.app/mcp?token=<token>`, Authentication **No authentication**.
Then in a chat enable the connector (⋯ → Developer mode → WooCommerce) and ask *"Which orders are on hold?"*.

**OpenAI API** (`gpt-6.1-sol`) — the Responses API calls remote MCP servers itself, headers included:
`OPENAI_API_KEY=… MCP_URL=https://woo-mcp-production-1b5f.up.railway.app/mcp WOO_MCP_TOKEN=<token> uv run --extra demo demo/openai_responses.py "Which orders are on hold?"`
(see [`demo/openai_responses.py`](../openai_responses.py)).

**pydantic-ai / scripts:**

```python
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset
agent = Agent("groq:openai/gpt-oss-120b",
              toolsets=[MCPToolset("https://woo-mcp-production-1b5f.up.railway.app/mcp",
                                   headers={"Authorization": "Bearer <token>"})])
```

Health without auth: `https://woo-mcp-production-1b5f.up.railway.app/healthz`.
