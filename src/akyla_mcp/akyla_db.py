"""Map an OAuth-verified identity (email) to an Akyla API key.

Only used on the OAuth (ChatGPT) path. Given a Google-verified email:
  * known Akyla user  → mint them a dedicated `mcp-oauth` API key at the plan their
    subscription entitles them to (license 'premium' or a 'trading' subscription → pro,
    else free — mirrors `planForUser` in the app),
  * unknown email     → auto-provision a free-tier account first (mirrors the app's
    magic-link signup shape), then mint. Google already verified the email, so the
    account is created verified.

Prior `mcp-oauth` keys are revoked on mint so keys don't pile up. We only ever store
the SHA-256 hash in the DB — the plaintext is held in memory per email (with a TTL,
so plan changes are re-checked on re-auth; Stripe webhooks also sync live key rows
directly, which covers mid-session upgrades).

Requires a DB connection (env AKYLA_DB_DSN or the standard PG* vars). No-ops cleanly if
asyncpg or the DSN is absent, so the key-auth path is unaffected.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import secrets
import time

# Quota / per-minute rate per plan. Mirror of the app's PLAN_LIMITS
# (private/frontend app/utils/server/apiKeys.server.ts) — keep in sync.
PLAN_LIMITS: dict[str, tuple[int, int]] = {
    "free": (1_000, 10),
    "pro": (500_000, 300),
}

# Re-check the user's plan (and re-mint) after this long, so an upgrade done on the
# website is picked up by a fresh chat session without a server restart.
_CACHE_TTL_SECONDS = 15 * 60

# email -> (plaintext key, monotonic expiry)
_cache: dict[str, tuple[str, float]] = {}


def _db_enabled() -> bool:
    # Either a full DSN, or standard libpq env vars (PGHOST/PGUSER/PGPASSWORD/PGDATABASE)
    # that asyncpg.connect() reads automatically.
    return bool(os.environ.get("AKYLA_DB_DSN") or os.environ.get("PGHOST"))


def _generate_key() -> tuple[str, str, str]:
    """Mirror the app's generateApiKey(): ak_live_ + 32B base64url, sha256 hash."""
    raw = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    plaintext = f"ak_live_{raw}"
    prefix = f"ak_live_{raw[:8]}"
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    return plaintext, prefix, key_hash


def plan_for_account(license_: str | None, subscriptions: list[str] | None) -> str:
    """Mirror of the app's planForUser(): any paid subscriber runs at Pro."""
    paid = license_ == "premium" or "trading" in (subscriptions or [])
    return "pro" if paid else "free"


async def _notify_slack_signup(email: str) -> None:
    """Fire-and-forget Slack ping mirroring the app's signup notification.
    No-ops unless the Slack env vars are present; never raises."""
    token = os.environ.get("SLACK_BOT_OAUTH_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL_VPN_NOTIS") or os.environ.get("SLACK_CHANNEL")
    if not (token and channel):
        return
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "channel": channel,
                    "text": (
                        "New user registered via MCP OAuth (ChatGPT)\n"
                        f"- Email: {email}\n"
                        f"- Time: {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC"
                    ),
                },
            )
    except Exception:  # nosec B110 — best-effort notification only
        pass


async def key_for_email(email: str) -> str | None:
    """Return a usable Akyla key for this verified email, provisioning a free-tier
    account if the email is new. None only when the DB path is unavailable."""
    if not email:
        return None
    email = email.strip().lower()
    cached = _cache.get(email)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    if not _db_enabled():
        return None

    import asyncpg  # imported lazily so the key-auth path needs no DB driver

    # dsn=None → asyncpg reads standard PG* env vars.
    conn = await asyncpg.connect(dsn=os.environ.get("AKYLA_DB_DSN"))
    try:
        row = await conn.fetchrow(
            "SELECT user_id, tenant, license, subscriptions FROM users WHERE lower(email) = $1",
            email,
        )
        if row is None:
            # Auto-provision a free account for the Google-verified email, mirroring
            # the app's magic-link signup shape. ON CONFLICT guards the concurrent-
            # login race; the follow-up SELECT covers that path.
            row = await conn.fetchrow(
                "INSERT INTO users "
                "(user_id, email, login_method, first_name, last_name, license, tenant, "
                " is_verified, last_login) "
                "VALUES (gen_random_uuid(), $1, 'google', '', '', 'free', 'app', true, now()) "
                "ON CONFLICT (email) DO NOTHING "
                "RETURNING user_id, tenant, license, subscriptions",
                email,
            )
            if row is None:
                row = await conn.fetchrow(
                    "SELECT user_id, tenant, license, subscriptions "
                    "FROM users WHERE lower(email) = $1",
                    email,
                )
                if row is None:  # cannot happen barring DB failure
                    return None
            else:
                asyncio.get_running_loop().create_task(_notify_slack_signup(email))

        plan = plan_for_account(row["license"], row["subscriptions"])
        quota, rate = PLAN_LIMITS[plan]
        plaintext, prefix, key_hash = _generate_key()
        # Retire any prior mcp-oauth key for this user, then mint one at their plan.
        await conn.execute(
            "UPDATE api_keys SET revoked_at = now() "
            "WHERE user_id = $1 AND name = 'mcp-oauth' AND revoked_at IS NULL",
            row["user_id"],
        )
        await conn.execute(
            "INSERT INTO api_keys "
            "(id,user_id,tenant,name,key_prefix,key_hash,plan,monthly_quota,"
            " rate_limit_per_min,scopes,created_at,updated_at) VALUES "
            "(gen_random_uuid(),$1,$2,'mcp-oauth',$3,$4,$5,$6,$7,'{}',now(),now())",
            row["user_id"],
            row["tenant"],
            prefix,
            key_hash,
            plan,
            quota,
            rate,
        )
    finally:
        await conn.close()

    _cache[email] = (plaintext, time.monotonic() + _CACHE_TTL_SECONDS)
    return plaintext
