# SICRY — Tor/Onion Network Access Layer for AI Agents

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/JacobJandon/Sicry/blob/main/LICENSE)

**by JacobJandon** &nbsp;·&nbsp; [github.com/JacobJandon/Sicry](https://github.com/JacobJandon/Sicry)

One Python file. Drop it into any project and your AI agent gets full access to the Tor/.onion dark web — the same clean tool interface agents use for the regular internet, just now for hidden services.

Robin's complete search engine catalogue (18 engines) and OSINT pipeline are baked in directly. No Robin install needed. No extra processes. No config beyond a `.env` file.

```
pip install requests[socks] beautifulsoup4 python-dotenv stem
apt install tor && tor &
cp .env.example .env   # add one API key (or use Ollama — no key needed)
python sicry.py check  # → CONNECTED via Tor  |  exit IP: 185.220.101.5
```

---

## Contents

1. [What SICRY does](#what-sicry-does)
2. [Installation](#installation)
3. [Quickstart](#quickstart)
4. [All nine functions](#all-nine-functions)
5. [Tool schemas (Anthropic / OpenAI / Gemini)](#tool-schemas)
6. [Framework integration](#framework-integration)
7. [CLI reference](#cli-reference)
8. [The full OSINT pipeline](#the-full-osint-pipeline)
9. [Analysis modes](#analysis-modes)
10. [18 search engines](#18-search-engines)
11. [Environment variables](#environment-variables)
12. [Tor setup](#tor-setup)
13. [Troubleshooting](#troubleshooting)
14. [Credits](#credits)

---

## What SICRY does

SICRY gives AI agents exactly 6 tools — the same 6 they already know how to use for the clearnet, just now running over Tor:

| SICRY tool | Clearnet equivalent | What it does |
|---|---|---|
| `sicry_check_tor` | health check | Verify Tor is active, get exit IP |
| `sicry_renew_identity` | reset session | Rotate circuit, get new exit node |
| `sicry_fetch` | `fetch_url()` / `browser_read_page()` | Read any URL or `.onion` via Tor |
| `sicry_search` | `web_search()` / `brave_search()` | Query 18 dark web search engines |
| `sicry_ask` | `analyze()` / `summarize()` | LLM OSINT report from raw content |
| `sicry_check_engines` | ping / health check | Latency + status for all 18 engines |

Plus three quality-improvement helpers (Robin patterns, call directly):

| Helper | What it does |
|---|---|
| `refine_query(query)` | LLM: natural language → ≤5-word dark web query |
| `filter_results(query, results)` | LLM: pick top 20 most relevant from all raw results |
| `scrape_all(urls)` | Concurrent batch-fetch → `{url: "title - text"}` dict |

---

## Installation

### Requirements

- Python 3.10+
- Tor daemon running locally
- pip packages (below)

### 1. Install Tor

**Linux (Debian/Ubuntu):**
```bash
apt install tor
tor &
```

**macOS:**
```bash
brew install tor
tor &
```

**Custom DataDirectory (recommended for `renew_identity`):**
```bash
cat > /tmp/sicry_tor.conf << 'EOF'
SocksPort 9050
ControlPort 9051
CookieAuthentication 1
DataDirectory /tmp/tor_data
EOF

tor -f /tmp/sicry_tor.conf &
```
When using a custom config, set `TOR_DATA_DIR=/tmp/tor_data` in your `.env`.

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

Or manually:
```bash
pip install requests[socks] beautifulsoup4 python-dotenv stem

# Optional — only needed if using the MCP server
pip install mcp

# Optional — only needed if using OpenAI/Anthropic/Gemini LLM backends
pip install openai          # for OpenAI
pip install anthropic       # for Anthropic/Claude
pip install google-generativeai  # for Gemini
```

### 3. Configure `.env`

```bash
cp .env.example .env
```

Minimum config — pick one LLM:
```dotenv
# No-key option (local inference):
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.2

# OpenAI:
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...

# Anthropic:
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Gemini:
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza...
```

> **Note:** `ask()`, `refine_query()`, and `filter_results()` need an LLM key. All other tools (`search`, `fetch`, `check_tor`, `renew_identity`, `check_search_engines`, `scrape_all`) work with no key at all.

---

## Quickstart

```bash
# Verify Tor is running
python sicry.py check
# → CONNECTED via Tor  |  exit IP: 185.220.101.5  |  error: None

# Search the dark web
python sicry.py search "ransomware data leak" --max 10

# Fetch a .onion page
python sicry.py fetch http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion

# Print tool schemas for your framework
python sicry.py tools                     # Anthropic format (default)
python sicry.py tools --format openai     # OpenAI format
python sicry.py tools --format gemini     # Gemini format

# Rotate Tor identity
python sicry.py renew

# Start MCP server (for Claude Desktop / Cursor / Zed)
python sicry.py serve
```

In Python:
```python
import sicry

# Verify Tor
print(sicry.check_tor())
# → {"tor_active": True, "exit_ip": "185.220.101.5", "error": None}

# Search
results = sicry.search("credential dump")
# → [{"title": "...", "url": "http://...onion/...", "engine": "Ahmia"}, ...]

# Fetch
page = sicry.fetch("http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion")
# → {"url": "...", "is_onion": True, "status": 200, "title": "Ahmia", "text": "...", "links": [...]}
```

---

## All nine functions

### `check_tor() → dict`

Verify Tor is running and the machine is routing through a Tor exit node.

```python
r = sicry.check_tor()
# {"tor_active": True, "exit_ip": "185.220.101.5", "error": None}
# {"tor_active": False, "exit_ip": None, "error": "connection refused"}
```

**Call this first.** All other network functions silently fail if Tor is down.

---

### `renew_identity() → dict`

Rotate the Tor circuit — get a new exit node and a fresh identity.

```python
r = sicry.renew_identity()
# {"success": True, "error": None}
```

Auth is attempted in order:
1. `TOR_CONTROL_PASSWORD` env var (if you set `HashedControlPassword` in torrc)
2. Cookie file from `TOR_DATA_DIR` env var
3. Cookie file from common system paths (`/tmp/tor_data`, `/var/lib/tor`, `~/.tor`, `/run/tor`)
4. Empty-string / null auth (Tor with no password at all)

**Works out of the box** with SICRY's recommended torrc (cookie auth). See [Tor setup](#tor-setup).

---

### `fetch(url) → dict`

Fetch any URL through Tor — works for clearnet and `.onion` hidden services.

```python
r = sicry.fetch("http://somemarket.onion/listings")
# {
#   "url":      "http://somemarket.onion/listings",
#   "is_onion": True,
#   "status":   200,
#   "title":    "Market Listings",
#   "text":     "Plain text, HTML stripped, up to 8000 chars",
#   "links":    [{"text": "Link label", "href": "http://..."}, ...],  # up to 80 links
#   "error":    None
# }
```

- URLs without `http://` / `https://` get `http://` prepended automatically.
- `text` is HTML-stripped, whitespace-collapsed, truncated to `MAX_CONTENT_CHARS` (default 8000).
- Always returns a dict — never raises.

---

### `search(query, engines=None, max_results=20, max_workers=8) → list[dict]`

Search across 18 dark web search engines simultaneously.

```python
# All 18 engines in parallel
results = sicry.search("leaked database credentials")
# [{"title": "...", "url": "http://...onion/...", "engine": "Ahmia"}, ...]

# Specific engines only
results = sicry.search("ransomware", engines=["Ahmia", "Tor66", "Ahmia-clearnet"])

# More results
results = sicry.search("bitcoin mixer", max_results=50)
```

- Results are deduplicated by URL across all engines.
- `engines` is case-insensitive. Unknown engine names are silently skipped.
- Always returns a list — never raises.

---

### `scrape_all(urls, max_workers=5) → dict`

Batch-fetch multiple pages concurrently and return `{url: content}` ready for an LLM.

```python
pages = sicry.scrape_all(search_results[:10])
# {
#   "http://site1.onion/page": "Page Title - full page text...(truncated)",
#   "http://site2.onion/page": "Page Title - full page text",
#   ...
# }
combined = "\n\n".join(pages.values())
```

- Input is the raw output of `search()` — list of `{"title", "url"}` dicts.
- Content is capped at 2000 chars per page with `...(truncated)` marker.
- Uses Robin's pattern: `"title - text"` format primes the LLM with context.
- Pages that fail are silently dropped (only reachable pages returned).

---

### `refine_query(query, provider=None) → str`

LLM-refine a natural language query into ≤5 focused words for dark web search engines.

```python
q = sicry.refine_query("I want to find ransomware groups that targeted hospitals in 2026")
# → "hospital ransomware 2026 leak"

q = sicry.refine_query("has acme.com appeared in any data breaches")
# → "acme.com breach credentials"
```

- Falls back to the original query if no LLM key is set. **Never raises**.
- This is a Robin pattern — dark web indexes respond much better to short keywords than natural language.
- Use before `search()` for significantly better results.

---

### `filter_results(query, results, provider=None) → list[dict]`

LLM-filter a list of search results to keep only the top 20 most relevant.

```python
best = sicry.filter_results("hospital ransomware 2026", raw_results)
# Returns at most 20 results, selected by the LLM for relevance
```

- Falls back to `results[:20]` if no LLM key is set. **Never raises**.
- Automatically retries with truncated titles if the LLM rate-limits on large payloads.
- Use after `search()` to reduce noise before scraping.

---

### `ask(content, query="", mode="threat_intel", custom_instructions="", provider=None) → str`

Analyse dark web content with an LLM and return a structured OSINT report.

```python
report = sicry.ask(
    content="\n\n".join(pages.values()),
    query="hospital ransomware groups",
    mode="ransomware",
)
print(report)  # Structured report: indicators, TTPs, threat actor profile, next steps
```

**Modes:**

| Mode | Alias | Focus |
|---|---|---|
| `threat_intel` | *(default)* | General OSINT — artifacts, insights, next steps |
| `ransomware` | `ransomware_malware` | Malware/C2/MITRE TTPs, victim orgs, detection |
| `personal_identity` | | PII/breach exposure, severity, protective actions |
| `corporate` | `corporate_espionage` | Leaked credentials/code/docs, IR steps |

```python
# Add custom focus to any mode
report = sicry.ask(
    content,
    mode="threat_intel",
    custom_instructions="Focus on cryptocurrency wallets and mixer services",
)
```

- If no LLM key is set, returns a `[SICRY: ...]` error string — **never raises**.
- Content is truncated to `MAX_CONTENT_CHARS` (default 8000) before sending to the LLM.

---

### `check_search_engines(max_workers=8) → list[dict]`

Ping all 18 engines via Tor and return per-engine status and latency.

```python
results = sicry.check_search_engines()
# [
#   {"name": "Ahmia",  "status": "up",   "latency_ms": 1240, "error": None},
#   {"name": "Kaizer", "status": "down", "latency_ms": None, "error": "timeout"},
#   ...
# ]

live = [r for r in results if r["status"] == "up"]
print(f"{len(live)}/18 engines alive")
fastest = min(live, key=lambda x: x["latency_ms"])
print(f"Fastest: {fastest['name']} ({fastest['latency_ms']}ms)")
```

- Results maintain the original engine order.
- Use before `search()` to avoid wasting time on dead engines.

---

## Tool schemas

SICRY exposes all 6 tools in the native format for each major framework. All three formats are always in sync.

```python
import sicry

sicry.TOOLS         # Anthropic / Claude format (input_schema)
sicry.TOOLS_OPENAI  # OpenAI function-calling format (type: "function")
sicry.TOOLS_GEMINI  # Google Gemini function declarations
```

Print any of them:
```bash
python sicry.py tools                   # Anthropic (default)
python sicry.py tools --format openai
python sicry.py tools --format gemini
```

Tools exposed:

| Tool name | Required args | Optional args |
|---|---|---|
| `sicry_check_tor` | *(none)* | |
| `sicry_renew_identity` | *(none)* | |
| `sicry_fetch` | `url` | |
| `sicry_search` | `query` | `max_results` (int), `engines` (list) |
| `sicry_ask` | `content` | `query`, `mode`, `custom_instructions` |
| `sicry_check_engines` | *(none)* | `max_workers` (int) |

---

## Framework integration

### dispatcher

All frameworks share one dispatcher — call it with the tool name and input dict:

```python
result = sicry.dispatch(tool_name, tool_input)
# Returns: dict | list | str  (matches the tool's documented return type)
# Raises:  ValueError if tool_name is unknown
```

---

### Anthropic / Claude

```python
import anthropic, sicry, json

client = anthropic.Anthropic()
messages = [{"role": "user", "content": "Search dark web for recent credential leaks from banks"}]

while True:
    resp = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system="You are a dark-web OSINT analyst. Always verify Tor before searching.",
        tools=sicry.TOOLS,              # <- Anthropic format
        messages=messages,
    )

    if resp.stop_reason != "tool_use":
        print(next(b.text for b in resp.content if hasattr(b, "text")))
        break

    tool_results = []
    for block in resp.content:
        if block.type == "tool_use":
            result = sicry.dispatch(block.name, block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, default=str),
            })

    messages.append({"role": "assistant", "content": resp.content})
    messages.append({"role": "user",      "content": tool_results})
```

---

### OpenAI / GPT

```python
from openai import OpenAI
import sicry, json

client = OpenAI()
messages = [
    {"role": "system", "content": "You are a dark-web OSINT analyst."},
    {"role": "user",   "content": "Has acme.com appeared in any dark web leaks?"},
]

while True:
    resp = client.chat.completions.create(
        model="gpt-4o",
        tools=sicry.TOOLS_OPENAI,       # <- OpenAI format
        messages=messages,
    )
    msg = resp.choices[0].message
    messages.append(msg)

    if not msg.tool_calls:
        print(msg.content)
        break

    for call in msg.tool_calls:
        result = sicry.dispatch(
            call.function.name,
            json.loads(call.function.arguments),
        )
        messages.append({
            "role": "tool",
            "tool_call_id": call.id,
            "content": json.dumps(result, default=str),
        })
```

---

### Google Gemini

```python
import google.generativeai as genai
import sicry, json

genai.configure(api_key="YOUR_GEMINI_API_KEY")

model = genai.GenerativeModel(
    "gemini-2.5-flash",
    tools=[{"function_declarations": sicry.TOOLS_GEMINI}],   # <- Gemini format
    system_instruction="You are a dark-web OSINT analyst.",
)

chat = model.start_chat()
resp = chat.send_message("Find mentions of acme.com on dark web forums")

while True:
    fn_calls = [p.function_call for p in resp.parts
                if hasattr(p, "function_call") and p.function_call.name]
    if not fn_calls:
        for part in resp.parts:
            if hasattr(part, "text"):
                print(part.text)
        break

    tool_responses = []
    for fn_call in fn_calls:
        result = sicry.dispatch(fn_call.name, dict(fn_call.args))
        tool_responses.append(
            genai.protos.Part(
                function_response=genai.protos.FunctionResponse(
                    name=fn_call.name,
                    response={"result": json.dumps(result, default=str)},
                )
            )
        )
    resp = chat.send_message(tool_responses)
```

---

### LangChain

```python
from langchain.tools import StructuredTool
from langchain.agents import initialize_agent, AgentType
from langchain_openai import ChatOpenAI
import sicry

tools = [
    StructuredTool.from_function(name="sicry_check_tor",
        func=sicry.check_tor,
        description="Verify Tor is active. Call before any dark web operation."),
    StructuredTool.from_function(name="sicry_renew_identity",
        func=sicry.renew_identity,
        description="Rotate Tor circuit — new exit node and identity."),
    StructuredTool.from_function(name="sicry_fetch",
        func=sicry.fetch,
        description="Fetch any URL or .onion hidden service via Tor."),
    StructuredTool.from_function(name="sicry_search",
        func=lambda query, max_results=20: sicry.search(query, max_results=max_results),
        description="Search 18 dark web engines. Returns title/url/engine list."),
    StructuredTool.from_function(name="sicry_ask",
        func=sicry.ask,
        description="Analyse dark web content. mode: threat_intel|ransomware|personal_identity|corporate"),
    StructuredTool.from_function(name="sicry_check_engines",
        func=sicry.check_search_engines,
        description="Ping all 18 search engines. Returns status + latency per engine."),
]

agent = initialize_agent(
    tools,
    ChatOpenAI(model="gpt-4o"),
    agent=AgentType.OPENAI_FUNCTIONS,
    verbose=True,
)
agent.run("Search the dark web for ransomware activity targeting the healthcare sector")
```

---

### CrewAI

```python
from crewai import Agent, Task, Crew
from langchain.tools import StructuredTool
import sicry

sicry_tools = [
    StructuredTool.from_function(name="sicry_check_tor",
        func=sicry.check_tor,
        description="Verify Tor is active."),
    StructuredTool.from_function(name="sicry_search",
        func=lambda query: sicry.search(query, max_results=20),
        description="Search 18 dark web engines."),
    StructuredTool.from_function(name="sicry_fetch",
        func=sicry.fetch,
        description="Fetch any .onion URL via Tor."),
    StructuredTool.from_function(name="sicry_ask",
        func=sicry.ask,
        description="LLM OSINT analysis. mode: threat_intel|ransomware|personal_identity|corporate"),
    StructuredTool.from_function(name="sicry_check_engines",
        func=sicry.check_search_engines,
        description="Ping all 18 search engines. Returns status + latency."),
]

analyst = Agent(
    role="Dark Web OSINT Analyst",
    goal="Investigate dark web threats and produce structured intelligence reports",
    backstory="Expert in dark web monitoring and threat intelligence",
    tools=sicry_tools,
    verbose=True,
)

task = Task(
    description="Search for ransomware groups targeting hospitals. Fetch top results and produce an intelligence report.",
    expected_output="Structured OSINT report with threat actors, TTPs, indicators, and next steps.",
    agent=analyst,
)

Crew(agents=[analyst], tasks=[task]).kickoff()
```

---

### MCP (Claude Desktop / Cursor / Zed)

Start the server:
```bash
python sicry.py serve
```

Add to `~/.config/claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "sicry": {
      "command": "python",
      "args": ["/absolute/path/to/sicry.py", "serve"]
    }
  }
}
```

Cursor (`settings.json`):
```json
"mcp.servers": {
  "sicry": {
    "command": "python /absolute/path/to/sicry.py serve"
  }
}
```

The 6 SICRY tools are registered automatically via FastMCP. Requires: `pip install mcp`

---

### OpenClaw

```bash
mkdir -p ~/.openclaw/workspace/skills/sicry
cp sicry.py openclaw_skill/SKILL.md ~/.openclaw/workspace/skills/sicry/
```

---

## CLI reference

```
python sicry.py <command> [options]
```

| Command | Options | Description |
|---|---|---|
| `check` | | Verify Tor is running, show exit IP |
| `renew` | | Rotate Tor circuit |
| `search <query>` | `--max N` (default 10), `--engine NAME` (repeatable) | Search dark web |
| `fetch <url>` | | Fetch URL via Tor, print text |
| `tools` | `--format anthropic\|openai\|gemini` | Print tool schemas as JSON |
| `serve` | | Start MCP server |

**Examples:**
```bash
python sicry.py check
python sicry.py renew
python sicry.py search "ransomware healthcare" --max 15
python sicry.py search "bitcoin mixer" --engine Ahmia --engine Tor66
python sicry.py fetch http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion
python sicry.py tools --format openai | python -m json.tool
python sicry.py serve
```

---

## The full OSINT pipeline

This is the recommended workflow. Each step applies a Robin pattern that makes a measurable difference in result quality:

```python
import sicry

# Step 1: Verify Tor
status = sicry.check_tor()
if not status["tor_active"]:
    raise RuntimeError(f"Tor not active: {status['error']}")
print(f"Tor active. Exit IP: {status['exit_ip']}")

# Step 2: Health-check engines (skip dead ones)
engine_status = sicry.check_search_engines()
live = [e for e in engine_status if e["status"] == "up"]
live_names = [e["name"] for e in live]
print(f"{len(live)}/18 engines alive: {', '.join(live_names[:5])}...")

# Step 3: Refine query (Robin quality pattern)
raw_query = "ransomware groups targeting hospital systems 2026"
query = sicry.refine_query(raw_query)
print(f"Refined: '{raw_query}' -> '{query}'")

# Step 4: Search (query only live engines in parallel)
raw_results = sicry.search(
    query,
    engines=live_names,   # skip engines we know are down
    max_results=50,
)
print(f"{len(raw_results)} raw results")

# Step 5: Filter to best 20 (Robin quality pattern)
best = sicry.filter_results(query, raw_results)
print(f"Filtered to {len(best)} most relevant")

# Step 6: Batch scrape concurrently
pages = sicry.scrape_all(best[:10], max_workers=5)
print(f"Scraped {len(pages)} pages")

# Step 7: OSINT analysis
combined = "\n\n".join(f"[{url}]\n{text}" for url, text in pages.items())
report = sicry.ask(
    combined,
    query=query,
    mode="ransomware",
    custom_instructions="Focus on victim organisations and ransom demands.",
)
print(report)

# Step 8: Rotate identity when done
sicry.renew_identity()
```

---

## Analysis modes

All four modes produce a structured sectioned report. Pass raw `.onion` text or `scrape_all()` output.

### `threat_intel` (default)

General dark web OSINT. Best for initial investigation.

Output sections: Input Query · Source Links · Investigation Artifacts · Key Insights · Next Steps

```python
report = sicry.ask(content, query="acme.com breach", mode="threat_intel")
```

### `ransomware`

Alias: `ransomware_malware`

Malware intelligence. Extracts C2 domains, file hashes, MITRE ATT&CK TTPs, victim sectors.

Output sections: Input Query · Source Links · Malware/Ransomware Indicators · Threat Actor Profile · Key Insights · Next Steps

```python
report = sicry.ask(content, query="LockBit hospital", mode="ransomware")
```

### `personal_identity`

PII exposure analysis. Surfaces SSNs, emails, passport data, breach sources, risk severity.

Output sections: Input Query · Source Links · Exposed PII Artifacts · Breach/Marketplace Sources · Exposure Risk Assessment · Key Insights · Next Steps

```python
report = sicry.ask(content, query="john.doe@email.com", mode="personal_identity")
```

### `corporate`

Alias: `corporate_espionage`

Corporate threat intelligence. Detects leaked credentials, source code, internal documents.

Output sections: Input Query · Source Links · Leaked Corporate Artifacts · Threat Actor/Broker Activity · Business Impact Assessment · Key Insights · Next Steps

```python
report = sicry.ask(content, query="acme.com corporate leak", mode="corporate")
```

---

## 18 search engines

Robin's full catalogue plus two verified additions. All queried simultaneously by `search()`.

| Engine | Type | Notes |
|---|---|---|
| **Ahmia** | `.onion` index | Most reliable, largest index |
| **OnionLand** | `.onion` index | |
| **Torgle** | `.onion` index | |
| **Amnesia** | `.onion` index | |
| **Kaizer** | `.onion` index | |
| **Anima** | `.onion` index | |
| **Tornado** | `.onion` index | |
| **TorNet** | `.onion` index | |
| **Torland** | `.onion` index | |
| **FindTor** | `.onion` index | |
| **Excavator** | `.onion` index | |
| **Onionway** | `.onion` index | |
| **Tor66** | `.onion` index | Good coverage of forums |
| **OSS** | `.onion` index | |
| **Torgol** | `.onion` index | |
| **TheDeepSearches** | `.onion` index | |
| **DuckDuckGo-Tor** | `.onion` (DDG) | PGP-verified address |
| **Ahmia-clearnet** | clearnet HTTPS | Ahmia's clearnet mirror — always reachable |

Use `check_search_engines()` before a large run to see which are alive.

Use `engines=["Ahmia", "Ahmia-clearnet"]` for fast reliable results, or omit `engines` for maximum coverage.

---

## Environment variables

Copy `.env.example` to `.env`. All variables are optional — configure only what you need.

| Variable | Default | Description |
|---|---|---|
| `TOR_SOCKS_HOST` | `127.0.0.1` | Tor SOCKS5 proxy host |
| `TOR_SOCKS_PORT` | `9050` | Tor SOCKS5 proxy port |
| `TOR_CONTROL_HOST` | `127.0.0.1` | Tor control port host |
| `TOR_CONTROL_PORT` | `9051` | Tor control port |
| `TOR_CONTROL_PASSWORD` | *(unset)* | Password for HashedControlPassword |
| `TOR_DATA_DIR` | *(unset)* | Path to Tor DataDirectory — used to find cookie file for `renew_identity` |
| `TOR_TIMEOUT` | `45` | Per-request timeout in seconds |
| `LLM_PROVIDER` | *(unset)* | `openai` / `anthropic` / `gemini` / `ollama` / `llamacpp` |
| `OPENAI_API_KEY` | *(unset)* | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model |
| `ANTHROPIC_API_KEY` | *(unset)* | Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-opus-4-6` | Anthropic model |
| `GEMINI_API_KEY` | *(unset)* | Google Gemini API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama API base URL |
| `OLLAMA_MODEL` | `llama3.2` | Ollama model name |
| `LLAMACPP_BASE_URL` | `http://127.0.0.1:8080` | llama.cpp server base URL |
| `SICRY_MAX_CHARS` | `8000` | Max characters of content passed to LLM |

**`TOR_DATA_DIR` is the most important Tor variable.** Set it to Tor's `DataDirectory` path so `renew_identity()` can find the cookie file for authentication.

---

## Tor setup

### Default system Tor

If you ran `apt install tor && tor &`, search, fetch, and check_tor work immediately. The control port may not be enabled by default.

Check if the control port is open:
```bash
ss -tlnp | grep 9051
```

If nothing shows, enable it:
```bash
echo "ControlPort 9051" >> /etc/tor/torrc
echo "CookieAuthentication 1" >> /etc/tor/torrc
systemctl restart tor
```

### SICRY's recommended torrc

For development — everything in `/tmp`, no system changes needed:

```
SocksPort 9050
ControlPort 9051
CookieAuthentication 1
DataDirectory /tmp/tor_data
```

```bash
tor -f /tmp/sicry_tor.conf &
```

Then in `.env`:
```dotenv
TOR_DATA_DIR=/tmp/tor_data
```

### Using a password instead of cookie

```bash
# Generate a hashed password
tor --hash-password "mypassword"
# -> 16:...hash...

# Add to torrc
HashedControlPassword 16:...hash...

# In .env
TOR_CONTROL_PASSWORD=mypassword
```

### How `renew_identity()` auth works

SICRY tries 4 authentication strategies, in order, until one succeeds:

1. **`TOR_CONTROL_PASSWORD`** — use env var as string password
2. **Cookie file from `TOR_DATA_DIR`** — read `$TOR_DATA_DIR/control_auth_cookie` as raw bytes
3. **Cookie from common system paths** — auto-discovers `/tmp/tor_data`, `/var/lib/tor`, `~/.tor`, `/run/tor`
4. **Null/empty auth** — for Tor with no control password set at all

If all four fail, returns `{"success": False, "error": "..."}` with a helpful message. **Never raises.**

---

## Troubleshooting

**`tor_active: False`**
```bash
# Is Tor running?
pgrep tor || tor &
# Is SOCKS port open?
ss -tlnp | grep 9050
```

**`renew_identity()` returns `success: False`**
```bash
# Is control port open?
ss -tlnp | grep 9051
# Does the cookie file exist?
ls /tmp/tor_data/control_auth_cookie   # custom torrc
ls /var/lib/tor/control_auth_cookie    # system Tor
# Set TOR_DATA_DIR=/path/to/DataDirectory in .env
```

**`.onion` fetch returns `status: 0`**
The hidden service is down or Tor is slow. Try another URL from `search()`, or call `check_search_engines()` first to confirm Tor is reachable.

**Search returns 0 results**
Dark web indexes go down frequently. Run `check_search_engines()` to find live engines, then pass them explicitly: `search(query, engines=["Ahmia", "Ahmia-clearnet"])`.

**`[SICRY: OPENAI_API_KEY not set...]`**
Set `LLM_PROVIDER=ollama` to use local inference with no key, or add the relevant key to `.env`. `search()`, `fetch()`, `check_tor()`, `renew_identity()`, `scrape_all()`, and `check_search_engines()` all work without any LLM key.

**Slow searches**
Tor has variable latency. Use `check_search_engines()` to find the fastest live engines. `engines=["Ahmia", "Ahmia-clearnet"]` is the fastest reliable configuration.

**Log spam / stem DEBUG output**
SICRY suppresses urllib3 and all stem sub-loggers (`stem`, `stem.control`, `stem.response`, `stem.socket`, `stem.connection`, `stem.util`) completely on import, set to CRITICAL with NullHandler and `propagate=False`. If you still see debug output, ensure you import `sicry` before configuring any root log handlers.

---

## Credits

- Search engine list and OSINT prompts from [Robin](https://github.com/apurvsinghgautam/robin) by [@apurvsinghgautam](https://github.com/apurvsinghgautam) — MIT licence
- Additional verified `.onion` addresses from [dark.fail](https://dark.fail) (PGP-verified)
- Tor: [torproject.org](https://www.torproject.org/)

---

## License

Apache 2.0 License — Copyright 2026 JacobJandon

See [LICENSE](LICENSE) for full text.

Use responsibly and lawfully.
