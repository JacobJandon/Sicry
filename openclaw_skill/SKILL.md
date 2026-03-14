# SICRY — Dark Web / Onion Network Access

SICRY gives you full access to the Tor network and .onion hidden services — the same way you can fetch URLs and search the regular internet, but now for the dark web.

## What you can do with SICRY

- **Search the dark web** across 16 .onion search engines simultaneously
- **Fetch any .onion page** and read its content (titles, text, links)
- **Analyze dark web content** using LLM-powered OSINT investigation modes
- **Rotate your Tor identity** to get a new exit node / new circuit
- **Verify Tor connectivity** before running operations

## When to use SICRY

Use SICRY tools whenever the user asks you to:
- Search the dark web, Tor, or .onion networks
- Investigate dark web markets, forums, leak sites, or hidden services
- Check if data/credentials/information has appeared on the dark web
- Fetch or read the content of a `.onion` URL
- Conduct OSINT investigations that require dark web coverage
- Monitor for mentions of a person, organization, or asset on the dark web

## Tools

### `sicry_check_tor`
Verify Tor is running. Call this first before any dark web operation.

### `sicry_search`
Search across all 16 .onion search indexes at once for a query. Returns deduplicated `{title, url, engine}` results. Works like `web_search` but for the dark web.

### `sicry_fetch`
Fetch the full content of any URL through Tor — works for .onion hidden services and normal websites. Returns `{title, text, links, status}`. Works like `browser_read_page` but via Tor.

### `sicry_ask`
Analyze raw dark web content with an LLM. Pass text from fetched pages and get a structured OSINT report. Modes: `threat_intel`, `ransomware`, `personal_identity`, `corporate`.

### `sicry_renew_identity`
Rotate the Tor circuit / get a new identity. Use this between investigation sessions.

## Typical flow

1. Call `sicry_check_tor` — confirm Tor is connected
2. Call `sicry_search` with the investigation query
3. Call `sicry_fetch` on relevant result URLs to get full page content
4. Call `sicry_ask` with the fetched content to generate a structured investigation report

## Setup

SICRY requires:
- Tor running locally: `apt install tor && tor` (or `brew install tor && tor`)
- Python: `pip install -r requirements.txt` in the SICRY directory
- At least one LLM API key in `.env` (or set `LLM_PROVIDER=ollama` for local)

## Important

SICRY is for lawful, authorized investigation use only — OSINT, security research, threat intelligence. Always tell the user you are routing requests through Tor and that activity is being conducted on the Tor network.
