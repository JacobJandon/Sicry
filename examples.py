"""
SICRY — Integration Examples
How to plug SICRY into any AI framework in <20 lines.

Sections:
  1. Recommended pipeline  (refine → search → filter → scrape → ask)
  2. Anthropic             (claude-opus-4-6)
  3. OpenAI                (gpt-4o)
  4. Gemini                (gemini-2.5-flash)
  5. LangChain / CrewAI
  6. MCP                   (Claude Desktop / Cursor / Zed)
  7. OpenClaw skill
  8. Direct Python
"""

# ─────────────────────────────────────────────────────────────────
# 1.  RECOMMENDED PIPELINE  (Robin-quality results over Tor)
# ─────────────────────────────────────────────────────────────────
import sicry

# 1a. Verify Tor is running before doing anything
status = sicry.check_tor()
assert status["tor_active"], f"Tor not active: {status.get('error')}"
print("Tor exit IP:", status["exit_ip"])

# 1b. Health-check all 18 engines (Robin health.py pattern)
# Find out which are alive and their latencies before wasting time on dead ones
engine_status = sicry.check_search_engines()
live = [s for s in engine_status if s["status"] == "up"]
print(f"{len(live)}/18 engines alive")
if live:
    fastest = min(live, key=lambda x: x["latency_ms"])
    print(f"Fastest: {fastest['name']} ({fastest['latency_ms']}ms)")

# 1b. Focus the query — LLM trims to ≤5 words, dark web indexes respond much better
query = "ransomware groups targeting hospitals 2026"
refined = sicry.refine_query(query)
print("Refined query:", refined)  # e.g. "hospital ransomware 2026 groups"

# 1c. Search 18 engines in parallel
raw_results = sicry.search(refined, max_results=50)
print(f"{len(raw_results)} raw results from 18 engines")

# 1d. Filter to the 20 most relevant (LLM-powered)
best_urls = sicry.filter_results(refined, raw_results)
print("Top results:", best_urls[:5])

# 1e. Batch-fetch pages concurrently
pages = sicry.scrape_all(best_urls[:10])
# pages = {"http://...onion/..": "Page Title - full text", ...}

# 1f. Structured OSINT report
combined_text = "\n\n".join(pages.values())
report = sicry.ask(
    combined_text,
    query=refined,
    mode="ransomware",
    custom_instructions="Focus on victim industries and ransom amounts if present.",
)
print(report)

# 1g. Rotate Tor identity when done
sicry.renew_identity()


# ─────────────────────────────────────────────────────────────────
# 2.  ANTHROPIC  (claude-opus-4-6 with SICRY tools)
# ─────────────────────────────────────────────────────────────────
import anthropic, sicry, json

client = anthropic.Anthropic()

SYSTEM = (
    "You are a dark-web OSINT analyst. "
    "Use SICRY tools to investigate user requests over Tor. "
    "Always verify Tor is active before searching."
)

messages = [{"role": "user", "content": "Search the dark web for recent ransomware group activity"}]

while True:
    resp = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=SYSTEM,
        tools=sicry.TOOLS,          # ← drop SICRY tools straight in
        messages=messages,
    )

    for block in resp.content:
        if hasattr(block, "text"):
            print(block.text)

    if resp.stop_reason != "tool_use":
        break

    tool_results = []
    for block in resp.content:
        if block.type == "tool_use":
            result = sicry.dispatch(block.name, block.input)   # ← one line
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result),
            })

    messages.append({"role": "assistant", "content": resp.content})
    messages.append({"role": "user", "content": tool_results})


# ─────────────────────────────────────────────────────────────────
# 3.  OPENAI  (gpt-4o with SICRY tools)
# ─────────────────────────────────────────────────────────────────
from openai import OpenAI
import sicry, json

client = OpenAI()

SYSTEM = (
    "You are a dark-web OSINT analyst. "
    "Use SICRY tools over Tor. Verify Tor first, then search."
)

messages = [
    {"role": "system", "content": SYSTEM},
    {"role": "user",   "content": "Has my company domain acme.com appeared in any dark web leaks?"},
]

while True:
    resp = client.chat.completions.create(
        model="gpt-4o",
        tools=sicry.TOOLS_OPENAI,   # ← OpenAI format
        messages=messages,
    )
    msg = resp.choices[0].message
    messages.append(msg)

    if not msg.tool_calls:
        print(msg.content)
        break

    for call in msg.tool_calls:
        result = sicry.dispatch(call.function.name, json.loads(call.function.arguments))
        messages.append({
            "role": "tool",
            "tool_call_id": call.id,
            "content": json.dumps(result),
        })


# ─────────────────────────────────────────────────────────────────
# 4.  GEMINI  (gemini-2.5-flash with SICRY tools)
# ─────────────────────────────────────────────────────────────────
import google.generativeai as genai
import sicry, json

genai.configure(api_key="YOUR_GEMINI_API_KEY")

model = genai.GenerativeModel(
    "gemini-2.5-flash",
    tools=[{"function_declarations": sicry.TOOLS_GEMINI}],   # ← Gemini format
    system_instruction=(
        "You are a dark-web OSINT analyst. "
        "Use SICRY tools over Tor. Verify Tor first, then search."
    ),
)

chat = model.start_chat()
resp = chat.send_message("Find any mentions of the domain acme.com on dark web forums")

while True:
    fn_calls = [p.function_call for p in resp.parts if hasattr(p, "function_call") and p.function_call.name]
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
                    response={"result": json.dumps(result)},
                )
            )
        )
    resp = chat.send_message(tool_responses)


# ─────────────────────────────────────────────────────────────────
# 5.  LANGCHAIN / CREWAI  (any model via StructuredTool)
# ─────────────────────────────────────────────────────────────────
from langchain.tools import StructuredTool
import sicry

sicry_tools = [
    StructuredTool.from_function(
        name="sicry_check_tor",
        description="Check if Tor is running and return the exit IP address",
        func=sicry.check_tor,
    ),
    StructuredTool.from_function(
        name="sicry_search",
        description="Search the dark web across 18 .onion and Tor-accessible search engines",
        func=lambda query, max_results=20: sicry.search(query, max_results=max_results),
    ),
    StructuredTool.from_function(
        name="sicry_fetch",
        description="Fetch any .onion URL or clearnet URL through Tor",
        func=sicry.fetch,
    ),
    StructuredTool.from_function(
        name="sicry_ask",
        description="Analyze dark web content with LLM OSINT modes (threat_intel, ransomware, personal_identity, corporate)",
        func=sicry.ask,
    ),
    StructuredTool.from_function(
        name="sicry_renew_identity",
        description="Rotate the Tor circuit to get a new exit node and IP address",
        func=sicry.renew_identity,
    ),
    StructuredTool.from_function(
        name="sicry_check_engines",
        description="Ping all 18 search engines via Tor. Returns status and latency per engine.",
        func=sicry.check_search_engines,
    ),
]

# LangChain:
# from langchain.agents import initialize_agent, AgentType
# from langchain_openai import ChatOpenAI
# agent = initialize_agent(sicry_tools, ChatOpenAI(model="gpt-4o"), agent=AgentType.OPENAI_FUNCTIONS)
# agent.run("Search dark web for ransomware activity")

# CrewAI:
# from crewai import Agent, Task, Crew
# analyst = Agent(role="OSINT Analyst", goal="Investigate dark web", tools=sicry_tools, llm=...)
# task = Task(description="Find ransomware groups targeting healthcare", agent=analyst)
# Crew(agents=[analyst], tasks=[task]).kickoff()


# ─────────────────────────────────────────────────────────────────
# 6.  MCP  (Claude Desktop / Cursor / Zed / any MCP client)
# ─────────────────────────────────────────────────────────────────
# Start the server:
#   python sicry.py serve
#
# Add to ~/.config/claude/claude_desktop_config.json:
# {
#   "mcpServers": {
#     "sicry": {
#       "command": "python",
#       "args": ["/absolute/path/to/sicry.py", "serve"]
#     }
#   }
# }
#
# The agent sees six tools: sicry_check_tor, sicry_search, sicry_fetch, sicry_ask, sicry_renew_identity, sicry_check_engines
# No further setup needed — SICRY registers them automatically via FastMCP.


# ─────────────────────────────────────────────────────────────────
# 7.  OPENCLAW SKILL
# ─────────────────────────────────────────────────────────────────
# cp sicry.py openclaw_skill/SKILL.md ~/.openclaw/workspace/skills/sicry/
# The SKILL.md file describes the tools; OpenClaw uses them automatically.


# ─────────────────────────────────────────────────────────────────
# 8.  DIRECT PYTHON  (no framework — full Robin pipeline in 12 lines)
# ─────────────────────────────────────────────────────────────────
import sicry

# Tor check
assert sicry.check_tor()["tor_active"], "Start Tor first: tor &"

# Robin pipeline
q       = sicry.refine_query("credential leaks dark web 2025 finance")
results = sicry.search(q, max_results=40)
best    = sicry.filter_results(q, results)
pages   = sicry.scrape_all(best[:8])
report  = sicry.ask(
    "\n\n".join(pages.values()),
    query=q,
    mode="corporate",
    custom_instructions="Highlight any banking or financial institution mentions.",
)
print(report)
sicry.renew_identity()
