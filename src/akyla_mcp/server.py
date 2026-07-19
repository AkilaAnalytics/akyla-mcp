"""FastMCP server for the Akyla Financial Data API.

Seven tools, each a thin wrapper over one documented `/v1/*` endpoint. Tool names
and descriptions are written for reliable model selection: they say plainly that
this is US-equity data sourced from SEC filings, and that statements/fundamentals
can carry per-cell filing provenance so the model can *cite* every number.

Transports:
  * stdio  (default) — Claude Desktop, Claude Code, Cursor, Codex, Cline, Zed
  * http            — ChatGPT connectors, web clients, Smithery-hosted deploys

API key resolution order (per request):
  1. Authorization: Bearer <key>  /  X-Api-Key header  (remote/HTTP deployments)
  2. AKYLA_API_KEY environment variable                (local/stdio deployments)
"""

from __future__ import annotations

import argparse
import os
import re
from typing import Any, Literal

from fastmcp import FastMCP

try:  # ToolError renders as a clean tool failure to the client
    from fastmcp.exceptions import ToolError
except Exception:  # pragma: no cover - older/newer fastmcp
    ToolError = RuntimeError  # type: ignore[assignment,misc]

from .client import AkylaClient, AkylaError
from .config import Settings

INSTRUCTIONS = """\
Akyla Financial Data provides as-reported US-equity fundamentals sourced directly
from SEC inline-XBRL filings (10-K / 10-Q), plus live quotes, full financial
statements, valuation comps, and a screener over ~5-8k US stocks.

Use these tools when the user asks about a US public company's financials,
valuation, fundamentals, stock price, or wants to screen/compare stocks. Prefer
`get_fundamentals` for a fast headline snapshot; use `get_statement` with
provenance when the user needs auditable, citeable figures tied to a specific SEC
filing. Data is US equities only.\
"""

mcp = FastMCP("Akyla Financial Data", instructions=INSTRUCTIONS)

_client: AkylaClient | None = None


def _get_client() -> AkylaClient:
    global _client
    if _client is None:
        _client = AkylaClient(Settings.from_env())
    return _client


def _resolve_api_key() -> str | None:
    """For HTTP/remote deployments, accept a per-request key from the inbound
    Authorization: Bearer or X-Api-Key header. Returns None under stdio, where the
    key comes from the environment via the client."""
    try:
        from fastmcp.server.dependencies import get_http_headers

        headers = get_http_headers() or {}
    except Exception:
        return None
    # get_http_headers lower-cases keys, but be defensive.
    auth = headers.get("authorization") or headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return headers.get("x-api-key") or headers.get("X-Api-Key")


# A conservative ticker whitelist. Real symbols are short and alphanumeric with
# at most a single dot/dash (e.g. AAPL, BRK.B, BF-B). This also stops path-segment
# tricks like ".." from being interpolated into the request path.
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")


def _norm_ticker(ticker: str) -> str:
    clean = "".join(c for c in ticker.strip().upper() if c.isalnum() or c in ".-")
    if ".." in clean or not _TICKER_RE.match(clean):
        raise ToolError(
            f"Invalid ticker {ticker!r}. Use a US symbol like AAPL, MSFT, or BRK.B."
        )
    return clean


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    try:
        return await _get_client().get(path, params=params, api_key=_resolve_api_key())
    except AkylaError as exc:
        raise ToolError(str(exc)) from exc


# --------------------------------------------------------------------------- #
# Tools — one per documented endpoint.                                         #
# --------------------------------------------------------------------------- #


@mcp.tool()
async def get_quote(ticker: str, include_history: bool = False) -> dict:
    """Latest price snapshot and 52-week range for a US-listed stock.

    Args:
        ticker: US stock symbol, e.g. AAPL, MSFT, NVDA.
        include_history: If true, also return ~1 year of daily closes.
    """
    params = {"series": "1"} if include_history else None
    return await _get(f"/v1/quote/{_norm_ticker(ticker)}", params)


@mcp.tool()
async def get_fundamentals(ticker: str) -> dict:
    """Headline fundamentals for a US stock in one call: revenue, EBITDA, margins,
    EV/EBITDA, net debt and free cash flow, plus a live quote. Best first stop for
    "how is <company> doing / what are its fundamentals / is it cheap" questions.

    Args:
        ticker: US stock symbol, e.g. AAPL.
    """
    return await _get(f"/v1/fundamentals/{_norm_ticker(ticker)}")


@mcp.tool()
async def get_key_metrics(ticker: str) -> dict:
    """Full key-metrics table for a US stock across reporting periods (valuation,
    profitability, leverage, growth). Use when the user wants the detailed metric
    history rather than the single-call snapshot from get_fundamentals.

    Args:
        ticker: US stock symbol, e.g. AAPL.
    """
    return await _get(f"/v1/metrics/{_norm_ticker(ticker)}")


@mcp.tool()
async def get_statement(
    ticker: str,
    type: Literal["income", "balance", "cash"] = "income",
    provenance: bool = True,
) -> dict:
    """As-reported financial statement for a US stock, assembled straight from SEC
    inline-XBRL. With provenance on (default), every value carries its source — the
    SEC accession number and inline-XBRL fact id — so you can CITE each number to
    the primary filing. Use this when the user needs auditable figures.

    Args:
        ticker: US stock symbol, e.g. AAPL.
        type: Which statement — "income", "balance" (balance sheet), or "cash" (cash flow).
        provenance: Attach per-cell SEC filing attribution to every value. Keep true for citeable answers.
    """
    params = {"type": type}
    if provenance:
        params["provenance"] = "1"
    return await _get(f"/v1/statements/{_norm_ticker(ticker)}", params)


@mcp.tool()
async def get_notes(
    ticker: str, period: Literal["annual", "quarterly"] = "annual"
) -> dict:
    """Footnote disclosures (notes) from a US company's dimensional XBRL filings.

    Args:
        ticker: US stock symbol, e.g. AAPL.
        period: "annual" (10-K) or "quarterly" (10-Q).
    """
    return await _get(f"/v1/notes/{_norm_ticker(ticker)}", {"period": period})


@mcp.tool()
async def get_comps(ticker: str) -> dict:
    """Comparable companies for a US stock: the subject company plus peers with
    valuation multiples, for relative-valuation questions ("how does <company>
    compare to peers").

    Args:
        ticker: US stock symbol, e.g. AAPL.
    """
    return await _get(f"/v1/comps/{_norm_ticker(ticker)}")


@mcp.tool()
async def screen_equities(
    filters: dict[str, float] | None = None,
    sector: str | None = None,
    exchange: str | None = None,
    sort: str = "marketCap",
    order: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Screen ~5-8k US equities by valuation, size, growth and quality.

    Numeric filters use the form `<field>_<op>` where op is one of gt, gte, lt, lte.
    Values are in each field's native unit:
      - Money fields (marketCap, enterpriseValue, revenue, ebitda, netDebt, netIncome)
        are RAW USD — $10B is 10000000000, not 10000.
      - Ratios (pe, ps, evEbitda, evRevenue) are plain numbers.
      - Margins & growth (ebitdaMargin, fcfMargin, revenueGrowth, netIncomeGrowth)
        are decimals — 0.25 means 25%.
    Example — large, cheap companies:
        filters={"marketCap_gte": 10000000000, "pe_lte": 15}
    Common fields: marketCap, enterpriseValue, pe, ps, evEbitda, evRevenue, revenue,
    ebitda, ebitdaMargin, fcfMargin, revenueGrowth, netIncome, netDebt, price, volume.

    Args:
        filters: Mapping of "<field>_<op>" -> number, e.g. {"marketCap_gte": 1e10, "pe_lte": 20}.
        sector: Exact SIC industry description in UPPERCASE, e.g. "SEMICONDUCTORS & RELATED
                DEVICES". These are SIC labels, NOT GICS names — "Technology" matches nothing.
                Prefer numeric filters unless you know the exact SIC string.
        exchange: Restrict to an exchange, e.g. "NASDAQ" or "NYSE".
        sort: Field to sort by (default marketCap).
        order: "asc" or "desc".
        limit: Rows to return, 1-500 (default 50).
        offset: Rows to skip, for paging.
    """
    params: dict[str, Any] = {
        "sector": sector,
        "exchange": exchange,
        "sort": sort,
        "order": order,
        "limit": max(1, min(int(limit), 500)),
        "offset": max(0, int(offset)),
    }
    for key, value in (filters or {}).items():
        field, _, op = key.rpartition("_")
        if not field or op not in {"gt", "gte", "lt", "lte"}:
            raise ToolError(
                f"Invalid filter '{key}'. Use '<field>_<op>' with op in gt/gte/lt/lte, "
                "e.g. 'marketCap_gte'."
            )
        params[key] = value
    return await _get("/v1/screener", params)


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #


def main() -> None:
    parser = argparse.ArgumentParser(description="Akyla Financial Data MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get("AKYLA_MCP_TRANSPORT", "stdio"),
        help="stdio (local clients) or http (remote / ChatGPT / hosting). Default: stdio.",
    )
    # Bind loopback by default so `--transport http` doesn't expose the server to
    # the local network unintentionally. Containers/hosts that mean to expose it
    # (e.g. the Dockerfile, Smithery) set HOST=0.0.0.0 explicitly.
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PORT", "8000"))
    )
    args = parser.parse_args()

    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()  # stdio


if __name__ == "__main__":
    main()
