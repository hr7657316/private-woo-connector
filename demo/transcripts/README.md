# Transcripts

Saved runs of `demo/agent.py` against the seeded Docker store, produced with:

    MODEL=<provider:model> uv run --extra demo demo/agent.py "<question>" 2>/dev/null > demo/transcripts/<name>.md

| File | Model | Question |
|---|---|---|
| `groq-gpt-oss-120b-on-hold.md` | groq:openai/gpt-oss-120b | on-hold orders and their combined total |
| `groq-gpt-oss-120b-low-stock.md` | groq:openai/gpt-oss-120b | items at or below 5 units, including variations |
| `groq-gpt-oss-120b-customer.md` | groq:openai/gpt-oss-120b | Priya Nair's processing order and stock of its items |
| `groq-qwen3.8-27b-on-hold.md` | groq:qwen/qwen3.8-27b | same on-hold question, different model family |

Each file shows the tool calls the model chose (`→`), a preview of what came back (`←`), the final answer and
token usage. No credentials are included.
