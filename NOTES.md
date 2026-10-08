# Build notes

What the live store taught me that the docs did not, and the decisions behind the shape of the code.
Kept short on purpose - the kind of thing I'd put in a hand-over.

## Things only the real WooCommerce revealed

1. **OAuth1 HMAC key is `consumer_secret + "&"`.** OAuth 1.0a keys are `secret&token_secret`; WooCommerce has
   no token secret but keeps the trailing ampersand. My first implementation signed with the bare secret and the
   store answered *"Invalid signature - provided signature does not match"* while accepting the key. The fix was
   one line; finding it meant reading `WC_REST_Authentication::check_oauth_signature` out of the container.
   The unit test now pins the base-string algorithm and the integration test proves the store accepts it.

2. **`consumer_secret` is a `char(43)` column.** My demo secret was 48 characters; MariaDB in strict mode
   rejected the insert and `$wpdb->insert` returned `false` without raising, so the seed "succeeded" with no key.
   Real secrets are `cs_` + 40 hex = 43 chars. The seed now checks `$wpdb->last_error` and fails loudly.

3. **Setting a stock quantity equal to the cached value writes nothing.** WooCommerce persists only changed
   props. Orders reduce stock as they are created; resetting the quantity on the product object I already held
   (which still cached the original number) was a no-op, so the demo data drifted. Reload the product first.

4. **Order search matches first_name and last_name separately.** `search=Priya Nair` returns nothing; `Priya`
   works. gpt-oss recovered by retrying on its own, but a connector should not rely on that - `search_orders`
   retries a multi-word query with its first word and the tool description steers models to email/order number.

5. **Model catalogues move.** Groq had retired `llama-3.3-70b-versatile` by build time; pydantic-ai 2.x renamed
   the Google prefix to `google:` and reads `GOOGLE_API_KEY`. Every model id in the docs was re-verified against
   the vendor's catalogue on 2026-10-08.

6. **Reseeding shifts ids.** Adding one product to the seed moved every order number by +1 and made four eval
   expectations wrong while the model was right. The eval now resolves order numbers from the store at run time,
   and the canary product is created after the orders so ids stay stable across seeds.

7. **wc-auth needs an HTTPS callback and refuses local hosts.** `WC_Auth` throws unless `callback_url` is
   `https://`, and `wp_safe_remote_post` blocks non-external hosts and non-standard ports. The CLI serves the
   callback on a self-signed cert; the demo store carries a 20-line mu-plugin that relaxes exactly those checks
   for `host.docker.internal`. A production connector hosts a public HTTPS callback and needs none of it.

## Decisions

- **Read-only is the blast-radius control, not a limitation.** The injection canary in the seed asks the agent to
  cancel orders; the eval checks the store afterwards. There is nothing to call, so there is nothing to defend.
- **Trim payloads at the connector, not in the prompt.** A raw order is 2.6 KB; the summary is 0.6 KB. Twenty
  orders cost ~3k tokens instead of ~13k, and the model sees fields it can reason about. `verbose=true` keeps
  the escape hatch.
- **Throttle client-side even though WooCommerce does not.** Real stores sit behind WP Engine / Cloudflare and
  have few PHP workers; an agent burst is the most likely way to hurt a merchant. Token bucket + `Retry-After`.
- **Primitives are plain async functions; MCP is a thin layer.** The smoke script, the evals and the tools all
  call the same code, and a second merchant tool is a sibling module, not a rewrite.
- **Evals grade deterministically.** Substring checks on normalised answers plus live post-conditions. An
  LLM judge would be more flexible and less reproducible; for 13 questions with known answers, determinism wins.
- **Transcripts and results are committed.** A reviewer should not need an API key to see what the agent did.

## What I would do next (in order)

1. Eval the Anthropic / OpenAI / Gemini lines once keys are available; the harness already supports them.
2. Webhooks (`order.updated`, `product.updated`) feeding a per-merchant read model, so `list_*` and the
   low-stock scan stop hitting the store.
3. Write tools behind an approval gate and an audit log, issued through a separate read/write key.
4. Per-conversation call budget + structured logs per tool call.
