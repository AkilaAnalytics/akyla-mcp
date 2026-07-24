"""Offline tests — exercise tool registration, schema, and input validation
without hitting the network (no API key required)."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from akyla_mcp.server import _norm_ticker, mcp

EXPECTED_TOOLS = {
    "get_quote",
    "get_fundamentals",
    "get_key_metrics",
    "get_statement",
    "get_notes",
    "get_comps",
    "screen_equities",
}


@pytest.mark.asyncio
async def test_all_tools_register():
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_statement_schema_enum_and_provenance():
    async with Client(mcp) as client:
        stmt = next(t for t in await client.list_tools() if t.name == "get_statement")
    props = stmt.inputSchema["properties"]
    assert props["type"]["enum"] == ["income", "balance", "cash"]
    assert props["provenance"]["default"] is True


@pytest.mark.asyncio
async def test_missing_key_is_actionable():
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="API key"):
            await client.call_tool("get_quote", {"ticker": "AAPL"})


@pytest.mark.asyncio
async def test_bad_screener_filter_rejected():
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="Invalid filter"):
            await client.call_tool("screen_equities", {"filters": {"marketCap_between": 5}})


@pytest.mark.asyncio
async def test_tools_marked_read_only():
    async with Client(mcp) as client:
        tools = await client.list_tools()
    for t in tools:
        assert t.annotations is not None and t.annotations.readOnlyHint is True, t.name


@pytest.mark.asyncio
async def test_prompts_registered():
    async with Client(mcp) as client:
        names = {p.name for p in await client.list_prompts()}
    assert {"stock_snapshot", "compare_peers", "cited_statement"} <= names


def test_key_from_query_string():
    from akyla_mcp.auth import key_from_query_string

    assert key_from_query_string(b"apiKey=ak_live_x") == "ak_live_x"
    assert key_from_query_string(b"akylaApiKey=ak_live_y&z=1") == "ak_live_y"
    assert key_from_query_string(b"foo=bar") is None


@pytest.mark.asyncio
async def test_akyla_key_verifier():
    from akyla_mcp.auth import AkylaKeyVerifier

    v = AkylaKeyVerifier()
    tok = await v.verify_token("ak_live_z")
    assert tok is not None and tok.claims["akyla_api_key"] == "ak_live_z"
    assert await v.verify_token("eyJhbGciOi") is None  # a JWT falls through to Google


def test_generate_key_format():
    from akyla_mcp.akyla_db import _generate_key

    plaintext, prefix, key_hash = _generate_key()
    assert plaintext.startswith("ak_live_") and prefix.startswith("ak_live_")
    assert len(key_hash) == 64 and plaintext.startswith(prefix)


@pytest.mark.parametrize("good", ["AAPL", "aapl", "BRK.B", "BF-B", "MSFT"])
def test_valid_tickers(good):
    assert _norm_ticker(good) == good.upper()


@pytest.mark.parametrize("bad", ["..", "../../etc", "", "   ", "@#$"])
def test_path_traversal_and_junk_rejected(bad):
    with pytest.raises(ToolError):
        _norm_ticker(bad)


def test_plan_for_account_mirrors_app():
    from akyla_mcp.akyla_db import plan_for_account

    assert plan_for_account("premium", []) == "pro"
    assert plan_for_account("free", ["trading"]) == "pro"
    assert plan_for_account("free", ["vpn"]) == "free"
    assert plan_for_account("free", None) == "free"
    assert plan_for_account(None, None) == "free"


def _mock_client(handler):
    import httpx

    from akyla_mcp.client import AkylaClient
    from akyla_mcp.config import Settings

    c = AkylaClient(Settings(api_key=None, base_url="https://api.test", timeout=5))
    c._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.test"
    )
    return c


@pytest.mark.asyncio
async def test_429_quota_exceeded_sells_upgrade():
    import httpx

    from akyla_mcp.client import AkylaError

    def handler(request):
        return httpx.Response(429, json={"error": {"code": "quota_exceeded"}})

    c = _mock_client(handler)
    with pytest.raises(AkylaError, match=r"\$19/mo"):
        await c.get("/v1/quote/AAPL", api_key="ak_live_t")
    await c.aclose()


@pytest.mark.asyncio
async def test_429_rate_limited_says_back_off():
    import httpx

    from akyla_mcp.client import AkylaError

    def handler(request):
        return httpx.Response(429, json={"error": {"code": "rate_limited"}})

    c = _mock_client(handler)
    with pytest.raises(AkylaError, match="Wait about 30 seconds"):
        await c.get("/v1/quote/AAPL", api_key="ak_live_t")
    await c.aclose()
