# Akyla Financial Data — MCP server

[![PyPI](https://img.shields.io/pypi/v/akyla-mcp)](https://pypi.org/project/akyla-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/akyla-mcp)](https://pypi.org/project/akyla-mcp/)
[![CI](https://github.com/AkilaAnalytics/akyla-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/AkilaAnalytics/akyla-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/pypi/l/akyla-mcp)](./LICENSE)

Give your AI **cited** financial data. This is a [Model Context Protocol](https://modelcontextprotocol.io)
server for the [Akyla Financial Data API](https://akyla.ai/products/financial-data-api):
as-reported US-equity fundamentals sourced straight from **SEC inline-XBRL filings**,
plus live quotes, full financial statements, valuation comps, and a screener over
~5–8k US stocks.

Because statement values carry **per-cell filing provenance** (SEC accession number +
XBRL fact id), the model can point at the exact 10-K/10-Q behind every number —
instead of guessing.

Works in **Claude Desktop, Claude Code, ChatGPT, Cursor, Codex, Cline, Zed** — anything
that speaks MCP.

## Tools

| Tool | What it does |
|---|---|
| `get_quote` | Latest price + 52-week range (optionally ~1yr of daily closes) |
| `get_fundamentals` | Revenue, EBITDA, margins, EV/EBITDA, net debt, FCF + live quote, in one call |
| `get_key_metrics` | Full key-metrics table across reporting periods |
| `get_statement` | Income / balance sheet / cash flow, as-reported, with per-cell SEC provenance |
| `get_notes` | Footnote disclosures from dimensional XBRL (annual/quarterly) |
| `get_comps` | Subject company + peers with valuation multiples |
| `screen_equities` | Filter ~5–8k US equities by valuation, size, growth, quality |

## Prompts

Ready-made workflows over the tools:

| Prompt | What it does |
|---|---|
| `stock_snapshot` | Fast fundamental read — fundamentals + quote, summarized |
| `compare_peers` | Relative valuation vs comparable companies |
| `cited_statement` | Pull a statement with SEC provenance and cite every figure |

## Get a key

Free tier: 1,000 calls/month, no credit card → https://app.akyla.ai/developers

## Install

### Claude Code

```bash
claude mcp add akyla --env AKYLA_API_KEY=ak_live_xxx -- uvx akyla-mcp
```

### Claude Desktop

Settings → Developer → Edit Config, then add:

```json
{
  "mcpServers": {
    "akyla": {
      "command": "uvx",
      "args": ["akyla-mcp"],
      "env": { "AKYLA_API_KEY": "ak_live_xxx" }
    }
  }
}
```

(Or install the one-click Desktop Extension — see [`manifest.json`](./manifest.json).)

### Cursor / Windsurf / Cline / Codex

Same shape as above in the client's MCP config:

```json
{
  "mcpServers": {
    "akyla": {
      "command": "uvx",
      "args": ["akyla-mcp"],
      "env": { "AKYLA_API_KEY": "ak_live_xxx" }
    }
  }
}
```

### ChatGPT / web clients (remote)

Run the server over HTTP and add it as a connector:

```bash
AKYLA_API_KEY=ak_live_xxx uvx akyla-mcp --transport http --port 8000
# serves MCP at http://localhost:8000/mcp
```

For a hosted, multi-tenant deployment, each request's key is read from the
`Authorization: Bearer <key>` or `X-Api-Key` header (falling back to `AKYLA_API_KEY`).
See [`smithery.yaml`](./smithery.yaml) and [`Dockerfile`](./Dockerfile).

## Local development

```bash
uv sync
cp .env.example .env      # add your key
uv run akyla-mcp                       # stdio
uv run akyla-mcp --transport http      # remote

# inspect with the MCP Inspector
npx @modelcontextprotocol/inspector uv run akyla-mcp
```

## Try it

> "Pull Apple's latest income statement with SEC provenance and tell me FY revenue,
> citing the filing."
>
> "Screen for US companies over $10B market cap with EV/EBITDA under 12, sorted by revenue growth."

## Security

- **Your key stays local** in stdio mode — it lives in your client's own config and
  is sent only to `app.akyla.ai` over HTTPS. It is never logged.
- **Hosting the remote (HTTP) server:** each request should carry its own key via
  `Authorization: Bearer <key>` or `X-Api-Key`. **Do not set a shared `AKYLA_API_KEY`
  on a public multi-user endpoint** — anyone who can reach it would spend that key's
  quota. (Smithery isolates per-user config, so its hosted deploy is fine.)
- **Binding:** the server binds `127.0.0.1` by default. Only set `HOST=0.0.0.0`
  inside a container or a network you control (the `Dockerfile` does this).
- Ticker input is validated against a strict whitelist before use.

Found a security issue? Email security@akyla.ai rather than opening a public issue.

## License

MIT · Built by [Akyla](https://akyla.ai)
