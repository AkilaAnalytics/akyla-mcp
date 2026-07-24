"""Thin async HTTP client over the Akyla Financial Data API.

Every method is a direct wrapper of one documented `/v1/*` endpoint. Errors are
normalised into `AkylaError` with an actionable message so the calling LLM can
recover (e.g. prompt the user for a key, pick a valid ticker, or back off).
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


class AkylaError(RuntimeError):
    """A user-actionable failure talking to the Akyla API."""


class AkylaClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=settings.timeout,
            headers={"User-Agent": f"akyla-mcp/{settings.version}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        api_key: str | None = None,
    ) -> Any:
        key = api_key or self._settings.api_key
        if not key:
            raise AkylaError(
                "No Akyla API key configured. Set AKYLA_API_KEY (or send an "
                "Authorization: Bearer <key> header when using the remote server). "
                "Get a free key at https://app.akyla.ai/developers"
            )

        # Drop None-valued params so optional args don't send empty query strings.
        clean = {k: v for k, v in (params or {}).items() if v is not None}

        try:
            resp = await self._client.get(
                path, params=clean, headers={"Authorization": f"Bearer {key}"}
            )
        except httpx.RequestError as exc:  # network/DNS/timeout
            raise AkylaError(f"Could not reach the Akyla API: {exc}") from exc

        if resp.status_code == 401:
            raise AkylaError("Akyla API key rejected (401). Check the key is valid and active.")
        if resp.status_code == 404:
            raise AkylaError(
                "Not found (404) — the ticker is not covered (US equities only) or the path is wrong."
            )
        if resp.status_code == 429:
            # The API distinguishes the burst limiter from the monthly billing meter
            # via error.code ('rate_limited' | 'quota_exceeded').
            try:
                code = (resp.json().get("error") or {}).get("code", "")
            except Exception:
                code = ""
            if code == "quota_exceeded" or resp.headers.get("X-Quota-Remaining") == "0":
                raise AkylaError(
                    "Monthly call quota reached on the current Akyla plan. Tell the user: "
                    "upgrade to Starter ($19/mo — 500,000 calls/month at 300 requests/min) at "
                    "https://app.akyla.ai/developers to continue, or the quota resets at "
                    "the start of next month."
                )
            raise AkylaError(
                "Per-minute rate limit exceeded (429). Wait about 30 seconds and retry. "
                "For higher throughput, Starter ($19/mo) raises the limit to 300 requests/min: "
                "https://app.akyla.ai/developers"
            )
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("error") or resp.json().get("message") or ""
            except Exception:
                detail = resp.text[:200]
            raise AkylaError(f"Akyla API error {resp.status_code}: {detail}".strip())

        try:
            return resp.json()
        except ValueError as exc:
            raise AkylaError("Akyla API returned a non-JSON response.") from exc
