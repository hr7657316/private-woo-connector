#!/usr/bin/env bash
# Register the server with Claude Code for the current project (run from the repo root).
set -euo pipefail
claude mcp add woocommerce -- uv run --directory "$PWD" woo-mcp
echo "registered. Try: claude  ->  'which orders are on hold?'"
