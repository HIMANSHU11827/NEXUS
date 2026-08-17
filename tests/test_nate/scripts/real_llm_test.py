"""
REAL LLM TEST — NATE vs Raw Tool Calling with DeepSeek API
Measures actual: request size, latency, response quality
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

# Load .env
_env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

import requests

from nexus.capabilities.intelligence.nate.nate_engine import NATE

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = "deepseek-chat"
ENDPOINT = "https://api.deepseek.com/chat/completions"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

TOOLS = [
    {
        "name": "get_weather",
        "description": "Get current weather for any city worldwide. Returns temperature, humidity, wind speed, and conditions.",
        "parameters": {"type": "object", "properties": {"location": {"type": "string", "description": "City name e.g. Mumbai, London"}}, "required": ["location"]},
    },
    {
        "name": "get_stock_price",
        "description": "Get current stock price and market data for a ticker symbol. Returns price, change %, volume.",
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string", "description": "Stock ticker symbol e.g. AAPL, TSLA"}}, "required": ["ticker"]},
    },
    {
        "name": "send_email",
        "description": "Send an email to a recipient. Supports CC, BCC, and attachments via URL.",
        "parameters": {"type": "object", "properties": {"to": {"type": "string", "description": "Recipient email address"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject"]},
    },
    {
        "name": "search_web",
        "description": "Search the internet for real-time information on any topic. Returns top results with snippets.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Search query"}}, "required": ["query"]},
    },
    {
        "name": "add_calendar_event",
        "description": "Add an event to the user's calendar with title, date, time, duration, and optional attendees.",
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"}, "time": {"type": "string", "description": "HH:MM"}, "duration_minutes": {"type": "integer"}}, "required": ["title", "date"]},
    },
    {
        "name": "translate_text",
        "description": "Translate text from source language to target language. Supports 50+ languages.",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "source_lang": {"type": "string"}, "target_lang": {"type": "string"}}, "required": ["text", "target_lang"]},
    },
    {
        "name": "create_reminder",
        "description": "Create a reminder that will notify you at the specified time. Supports recurring reminders.",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "datetime": {"type": "string", "description": "YYYY-MM-DD HH:MM"}, "recurring": {"type": "boolean"}}, "required": ["text", "datetime"]},
    },
    {
        "name": "get_news",
        "description": "Get latest news headlines for a topic or category. Returns headlines, sources, and publish dates.",
        "parameters": {"type": "object", "properties": {"topic": {"type": "string"}, "category": {"type": "string", "enum": ["general", "tech", "business", "sports"]}}, "required": ["topic"]},
    },
    {
        "name": "calculate",
        "description": "Perform mathematical calculations including arithmetic, trigonometry, logarithms, and unit conversions.",
        "parameters": {"type": "object", "properties": {"expression": {"type": "string", "description": "Math expression like sin(45) + 2*3"}}, "required": ["expression"]},
    },
    {
        "name": "get_newsletter_summary",
        "description": "Get a summary of the latest AI newsletter. Returns highlights and key developments.",
        "parameters": {"type": "object", "properties": {"newsletter_name": {"type": "string", "description": "Name of newsletter"}, "date": {"type": "string"}}, "required": ["newsletter_name"]},
    },
]

QUERIES = [
    "What is the weather in Mumbai today?",
    "Get me the stock price of Tesla",
    "Search the web for latest AI news and add a calendar event for tomorrow to discuss",
    "Send an email to john@example.com about the project update",
]

def call_deepseek(messages, tools=None):
    payload = {"model": MODEL, "messages": messages, "max_tokens": 1024}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    t0 = time.time()
    resp = requests.post(ENDPOINT, json=payload, headers=HEADERS, timeout=60)
    t1 = time.time()
    return resp, t1 - t0


print("=" * 70)
print("  REAL LLM TEST: NATE vs Raw Tool Calling (DeepSeek API)")
print("=" * 70)
print(f"  Model: {MODEL}")
print()

# Setup NATE
nate = NATE()
for t in TOOLS:
    nate.register_tool(
        name=t["name"],
        description=t["description"],
        parameters=t["parameters"],
        required=t.get("required", []),
    )
nate.set_flow("start", "finish")

# Register healing strategies
nate.register_healing_strategy("retry", handler=lambda e: "retried")
nate.register_healing_strategy("backoff", handler=lambda e: "backoff applied")

for qi, query in enumerate(QUERIES):
    messages = [
        {"role": "system", "content": "You are a helpful assistant with access to tools. When you need information, call the appropriate tool."},
        {"role": "user", "content": query},
    ]

    print(f"\n{'=' * 70}")
    print(f"  QUERY {qi + 1}: {query}")
    print(f"{'=' * 70}")

    # === RAW (BEFORE) - all 10 tool schemas ===
    raw_tools = [{"type": "function", "function": {k: v for k, v in t.items()}} for t in TOOLS]
    raw_size = len(json.dumps(raw_tools))
    print("\n  [RAW - ALL 10 TOOLS]")
    print(f"  Schema size: {raw_size} chars")

    total_raw_latency = 0
    for attempt in range(2):
        resp, lat = call_deepseek(messages, raw_tools)
        total_raw_latency += lat
        if resp.status_code == 200:
            result = resp.json()
            raw_usage = result.get("usage", {})
            raw_choice = result["choices"][0]["message"]
            raw_has_tc = "tool_calls" in raw_choice and raw_choice["tool_calls"]
            raw_tc_count = len(raw_choice.get("tool_calls", []))
            print(f"  Latency:           {lat * 1000:.0f}ms")
            print(f"  Input tokens:      {raw_usage.get('prompt_tokens', '?')}")
            print(f"  Output tokens:     {raw_usage.get('completion_tokens', '?')}")
            print(f"  Tool calls:        {raw_tc_count}")
            break
        else:
            print(f"  API Error ({resp.status_code}): {resp.text[:200]}")

    # === NATE (AFTER) - compressed + lazy loaded ===
    schema = nate.get_schemas(query, provider="openai")
    nate_tools_formatted = schema.get("all", [])

    nate_size = len(json.dumps(nate_tools_formatted))
    print("\n  [NATE - COMPRESSED + LAZY LOADED]")
    print(f"  Schema size: {nate_size} chars")
    print(f"  Token saved: {raw_size - nate_size} chars ({round((1 - nate_size / raw_size) * 100, 1)}%)")

    total_nate_latency = 0
    for attempt in range(2):
        resp, lat = call_deepseek(messages, nate_tools_formatted)
        total_nate_latency += lat
        if resp.status_code == 200:
            result = resp.json()
            nate_usage = result.get("usage", {})
            nate_choice = result["choices"][0]["message"]
            nate_has_tc = "tool_calls" in nate_choice and nate_choice["tool_calls"]
            nate_tc_count = len(nate_choice.get("tool_calls", []))
            print(f"  Latency:           {lat * 1000:.0f}ms")
            print(f"  Input tokens:      {nate_usage.get('prompt_tokens', '?')}")
            print(f"  Output tokens:     {nate_usage.get('completion_tokens', '?')}")
            print(f"  Tool calls:        {nate_tc_count}")
            break
        else:
            print(f"  API Error ({resp.status_code}): {resp.text[:200]}")

    # === COMPARISON ===
    print(f"\n  {'=' * 50}")
    print(f"  {'METRIC':<30s} {'BEFORE (RAW)':>12s} {'AFTER (NATE)':>12s}")
    print(f"  {'=' * 50}")
    print(f"  {'Schema chars':<30s} {raw_size:>8d}     {nate_size:>8d}")
    r_in = raw_usage.get("prompt_tokens", 0) if resp.status_code == 200 else 0
    n_in = nate_usage.get("prompt_tokens", 0) if resp.status_code == 200 else 0
    r_lat = total_raw_latency / 2 * 1000 if resp.status_code == 200 else 0
    n_lat = total_nate_latency / 2 * 1000 if resp.status_code == 200 else 0
    print(f"  {'Input tokens':<30s} {r_in:>8d}     {n_in:>8d}")
    print(f"  {'Latency (avg ms)':<30s} {r_lat:>8.0f}     {n_lat:>8.0f}")
    if n_in and r_in:
        print(f"  {'Token savings':<30s} {'':>8s}     {round((1 - n_in / r_in) * 100, 1):>7.1f}%")

print(f"\n{'=' * 70}")
print("  TEST COMPLETE")
print(f"{'=' * 70}")
