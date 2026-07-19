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


@pytest.mark.parametrize("good", ["AAPL", "aapl", "BRK.B", "BF-B", "MSFT"])
def test_valid_tickers(good):
    assert _norm_ticker(good) == good.upper()


@pytest.mark.parametrize("bad", ["..", "../../etc", "", "   ", "@#$"])
def test_path_traversal_and_junk_rejected(bad):
    with pytest.raises(ToolError):
        _norm_ticker(bad)
