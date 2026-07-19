"""Runtime configuration, resolved from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import __version__

DEFAULT_BASE_URL = "https://app.akyla.ai"


@dataclass(frozen=True)
class Settings:
    """Server settings. A missing api_key is allowed here: for remote/HTTP
    deployments the key can arrive per-request via the Authorization or
    X-Api-Key header instead (see server._resolve_api_key)."""

    api_key: str | None
    base_url: str
    timeout: float
    version: str = __version__

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_key=os.environ.get("AKYLA_API_KEY") or None,
            base_url=os.environ.get("AKYLA_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            timeout=float(os.environ.get("AKYLA_TIMEOUT", "30")),
        )
