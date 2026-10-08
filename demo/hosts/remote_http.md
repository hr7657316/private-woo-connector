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

**pydantic-ai / scripts:**

```python
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset
agent = Agent("groq:openai/gpt-oss-120b",
              toolsets=[MCPToolset("https://woo-mcp-production-1b5f.up.railway.app/mcp",
                                   headers={"Authorization": "Bearer <token>"})])
```

Health without auth: `https://woo-mcp-production-1b5f.up.railway.app/healthz`.
