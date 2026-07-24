# MCP OAuth freemium — gaps A–C (2026-07-24)

Approved in conversation. Goal: any Google-verified user can connect via ChatGPT
(auto-provisioned free account), paying users get paid limits, quota exhaustion
sells the upgrade in-chat.

## Facts confirmed from private/frontend (source of truth)

- `PLAN_LIMITS`: free = 1,000/mo @ 10/min; **pro = 500,000/mo @ 300/min, $19/mo**
  (single unified paid plan; starter/business are legacy). Marketing page $29/$99 is STALE.
- Entitlement rule (`planForUser`): paid ⇔ `users.license = 'premium'` OR
  `'trading' ∈ users.subscriptions`. Stripe webhooks call `syncUserKeyPlans` which
  updates ALL live keys (incl. `mcp-oauth`) on upgrade/downgrade — so the minted key
  stays correct after plan changes without our involvement.
- New-user shape (mirrors magic-link signup): `login_method='google'`, `license='free'`,
  `tenant='app'`, empty names, `is_verified=true` (Google verified the email).
  DB enum types: `login_method`, `license_type`, `subscription[]`. `user_id` needs
  `gen_random_uuid()` (Prisma default is client-side).
- 429 body distinguishes `error.code = 'rate_limited'` vs `'quota_exceeded'`;
  headers `X-Quota-Remaining` etc.; upgrade page = app.akyla.ai/developers.
- Deployment: `docker.akyla.ai/akila-mcp` image, k8s `akyla-mcp.yaml`, PG env present.

## Tasks

- [x] **A. Auto-provision** (`akyla_db.py`): unknown verified email → INSERT user
      (free/app/google, ON CONFLICT-safe), optional Slack signup notification
      (SLACK_BOT_OAUTH_TOKEN + SLACK_CHANNEL_VPN_NOTIS/SLACK_CHANNEL, no-op if absent).
- [x] **B. Plan-aware minting** (`akyla_db.py`): read license+subscriptions, mint
      `mcp-oauth` key at the entitled plan's quota/rate; cache gets a 15-min TTL so
      re-auth picks up plan changes (webhook sync covers live keys meanwhile).
- [x] **C. Upgrade messaging** (`client.py`): split 429 into quota_exceeded → "upgrade
      to Pro $19/mo at https://app.akyla.ai/developers" vs rate_limited → back off.
- [x] Tests for plan mapping + 429 messages; keep bandit clean.
- [x] Bump 0.3.0, pytest + bandit, build/push amd64 image, update manifest tag,
      `kubectl apply`, verify live.

## Review (2026-07-24)

- Shipped as v0.3.0 (commit 40fbd32, pushed). 22/22 tests pass; bandit: only the
  pre-existing Low B110 in server.py. Image `docker.akyla.ai/akila-mcp:0.3.0`
  deployed; mcp.akyla.ai verified (401 unauth, OAuth discovery 200).
- Slack env vars are NOT in the k8s manifest yet — signup pings no-op until added.
- k8s manifest dir `private/k8s/akila/akyla-mcp/` is untracked in the private repo
  (pre-existing; left as-is).
- NOT yet verified: the full ChatGPT connect flow end-to-end (needs a browser
  session). PyPI 0.3.0 not published (remote-only changes; local stdio users
  unaffected) — publish alongside the next stdio-relevant change.
- Public explainer page shipped separately: akyla.ai/mcp (frontend v0.0.93).
