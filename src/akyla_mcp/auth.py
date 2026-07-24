"""Auth for the remote HTTP server. Enabled ONLY when GOOGLE_CLIENT_ID/SECRET are set,
so local/stdio and any deploy without those vars stay exactly as they were (key-only).

Two ways in, combined via MultiAuth:
  * Google OAuth (ChatGPT + OAuth clients) — verified email mapped to an Akyla key
    downstream (see akyla_db.key_for_email).
  * Akyla API key as a bearer credential (Claude, Cursor, Smithery). A middleware
    promotes `?apiKey=`/`config` query values into an Authorization header first, so
    header-less/URL-embedded clients keep working.
"""

from __future__ import annotations

import base64
import json
import os
from urllib.parse import parse_qs

from fastmcp.server.auth import AccessToken, MultiAuth, TokenVerifier
from fastmcp.server.auth.providers.google import GoogleProvider

BASE_URL = os.environ.get("AKYLA_MCP_BASE_URL", "https://mcp.akyla.ai")
_KEY_NAMES = ("akylaApiKey", "apiKey", "api_key", "AKYLA_API_KEY")
# Short scopes passed to GoogleProvider (it expands "email" to the full Google URL).
REQUIRED_SCOPES = ["openid", "email"]
# The EXPANDED form the server actually checks tokens against — the Akyla-key token must
# carry these so it clears the same scope gate Google tokens do.
_KEY_TOKEN_SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]


class AkylaKeyVerifier(TokenVerifier):
    """Accept an Akyla `ak_` key as a bearer credential. We don't validate it against
    the API here (that would burn a request per call); the actual tool call authenticates
    for real and returns 401 if the key is bad. Non-`ak_` tokens fall through to Google."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if token and token.startswith("ak_"):
            return AccessToken(
                token=token,
                client_id="akyla-key",
                scopes=list(_KEY_TOKEN_SCOPES),
                claims={"akyla_api_key": token},
            )
        return None


def key_from_query_string(qs: bytes) -> str | None:
    """Pull an Akyla key out of a raw query string (named param or base64 `config`)."""
    if not qs:
        return None
    params = parse_qs(qs.decode("latin-1"))
    for name in _KEY_NAMES:
        if params.get(name):
            return params[name][0]
    blob = (params.get("config") or [None])[0]
    if blob:
        try:
            data = json.loads(base64.b64decode(blob + "=" * (-len(blob) % 4)))
            for name in _KEY_NAMES:
                if data.get(name):
                    return data[name]
        except Exception:
            return None
    return None


class QueryKeyMiddleware:
    """ASGI middleware: if a request carries an Akyla key in the query string and no
    Authorization header, promote it to `Authorization: Bearer <key>` so the key
    verifier (and thus Smithery / URL-embedded-key clients) authenticate."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            headers = dict(scope.get("headers") or [])
            if b"authorization" not in headers:
                key = key_from_query_string(scope.get("query_string", b""))
                if key:
                    scope = dict(scope)
                    scope["headers"] = list(scope.get("headers") or []) + [
                        (b"authorization", f"Bearer {key}".encode())
                    ]
        await self.app(scope, receive, send)


def build_auth():
    """MultiAuth (key + Google) when OAuth env is present, else None (key-only, unchanged)."""
    cid = os.environ.get("GOOGLE_CLIENT_ID")
    csec = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not (cid and csec):
        return None
    google = GoogleProvider(
        client_id=cid,
        client_secret=csec,
        base_url=BASE_URL,
        redirect_path="/auth/callback",
        required_scopes=REQUIRED_SCOPES,
    )
    # Google OAuth is the server-facing provider (discovery, DCR, token routes);
    # the Akyla-key verifier additionally accepts ak_ bearer tokens.
    return MultiAuth(server=google, verifiers=AkylaKeyVerifier())
