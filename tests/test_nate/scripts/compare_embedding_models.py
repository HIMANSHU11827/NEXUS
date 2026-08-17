"""
NATE-Route: BGE-small-en-v1.5 vs all-MiniLM-L6-v2 comparison.
Both cached locally. Tests ranking accuracy, latency, path decisions.
Loads and tests one model at a time to avoid OOM.
"""
import gc
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
import numpy as np

from nexus.capabilities.intelligence.nate.adaptive_schema import NATE_Route

TOOLS = [
    ("get_weather", "Get current weather for any city worldwide. Returns temperature, humidity, wind speed, and conditions."),
    ("get_stock_price", "Get current stock price and market data for a ticker symbol. Returns price, change percent, volume."),
    ("send_email", "Send an email to a recipient. Supports CC, BCC, and attachments via URL."),
    ("search_web", "Search the internet for real-time information on any topic. Returns top results with snippets."),
    ("add_calendar_event", "Add an event to the users calendar with title, date, time, duration, and optional attendees."),
    ("translate_text", "Translate text from source language to target language. Supports 50 plus languages."),
    ("create_reminder", "Create a reminder that will notify you at the specified time. Supports recurring reminders."),
    ("get_news", "Get latest news headlines for a topic or category. Returns headlines, sources, and publish dates."),
    ("calculate", "Perform mathematical calculations including arithmetic, trigonometry, logarithms, and unit conversions."),
    ("get_newsletter_summary", "Get a summary of the latest AI newsletter. Returns highlights and key developments."),
]

# (label, query, expected_tool_names)
QUERIES = [
    ("tool:weather",  "What is the weather in Mumbai today?",          ["get_weather"]),
    ("tool:stock",    "Get me the stock price of Tesla",              ["get_stock_price"]),
    ("tool:search+calendar", "Search the web for AI news and add a calendar event for tomorrow",
                                                                       ["search_web", "add_calendar_event"]),
    ("tool:email",    "Send an email to john@example.com",            ["send_email"]),
    ("tool:translate","Translate bonjour to English",                 ["translate_text"]),
    ("tool:reminder", "Remind me to buy groceries at 5pm",            ["create_reminder"]),
    ("tool:news",     "What are the latest tech headlines?",          ["get_news"]),
    ("tool:calculate","What is 144 divided by 12?",                   ["calculate"]),
    ("tool:newsletter","Summarize the latest AI newsletter",          ["get_newsletter_summary"]),
    ("tool:weather+calendar", "Check weather in Paris and add umbrella reminder",
                                                                       ["get_weather", "create_reminder"]),
    ("chat:greeting", "Hello, how are you?",                          []),
    ("chat:opinion",  "What do you think about AI?",                  []),
    ("chat:joke",     "Tell me a joke",                               []),
    ("chat:advice",   "Can you give me advice on learning Python?",   []),
    ("chat:history",  "What happened in World War 2?",                []),
]


def test_model(model_name: str) -> dict:
    label = model_name.split("/")[-1] if "/" in model_name else model_name
    print(f"\n{'='*70}")
    print(f"  Testing: {label}")
    print(f"{'='*70}")
    t0 = time.time()
    r = NATE_Route(model_name=model_name)
    for name, desc in TOOLS:
        r.register_tool(name, desc)
    print(f"  Loaded in {time.time()-t0:.1f}s | Tools: {r.stats()['num_tools']}")

    results = {
        "model": label,
        "queries": [],
        "latencies_ms": [],
        "path1": 0, "path2": 0, "no_tool": 0,
        "tool_acc": 0, "tool_total": 0,
        "chat_acc": 0, "chat_total": 0,
        "top1_scores": [],
        "all_scores": [],
        "confidences": [],
    }

    for q_label, query, expected_tools in QUERIES:
        is_tool = len(expected_tools) > 0
        t1 = time.perf_counter()
        result = r.route(query)
        lat_ms = (time.perf_counter() - t1) * 1000
        results["latencies_ms"].append(lat_ms)
        results["confidences"].append(result["confidence"])
        path = result["path"]
        results[path if path != "no_tools" else "no_tool"] += 1

        tools = result["tools"]
        names = [t[0] for t in tools]
        top1 = names[0] if names else "(none)"

        if tools:
            results["top1_scores"].append(tools[0][1])
            results["all_scores"].extend([t[1] for t in tools])

        # Check if ALL expected tools appear in results
        if is_tool:
            results["tool_total"] += 1
            names_set = set(names)
            all_found = all(e in names_set for e in expected_tools)
            results["tool_acc"] += 1 if all_found else 0
        else:
            results["chat_total"] += 1
            if path == "no_tools":
                results["chat_acc"] += 1

        results["queries"].append({
            "label": q_label,
            "query": query[:60],
            "path": path,
            "confidence": result["confidence"],
            "relative_gap": result.get("relative_gap", 0),
            "top1": top1,
            "extra": names[1:] if len(names) > 1 else [],
            "expected": expected_tools,
            "all_found": all(e in names for e in expected_tools) if is_tool else None,
            "latency_ms": round(lat_ms, 1),
        })

        found_mark = "[OK]" if (is_tool and all(e in names for e in expected_tools)) or \
                             (not is_tool and path == "no_tools") else "[FAIL]"
        print(f"  {found_mark} {q_label:<22s} {path:<9s} conf={result['confidence']:.3f} "
              f"gap={result.get('relative_gap',0):.3f} top1={top1:<20s} {lat_ms:.0f}ms")
        if names[1:]:
            print(f"  {'':22s} extras: {', '.join(names[1:])}")

    # Free memory
    del r
    gc.collect()
    return results


def print_comparison(all_results: dict):
    models = list(all_results.keys())
    sep = "=" * 85
    print(f"\n\n{sep}")
    print("  NATE-ROUTE MODEL COMPARISON RESULT")
    print(f"{sep}")
    print(f"  {'Metric':<40s} {'all-MiniLM-L6-v2':>20s} {'BGE-small-en-v1.5':>20s}")
    print(f"{sep}")

    for model in models:
        r = all_results[model]
        r["tool_acc_pct"] = (r["tool_acc"] / max(r["tool_total"], 1)) * 100
        r["chat_acc_pct"] = (r["chat_acc"] / max(r["chat_total"], 1)) * 100
        r["lat_mean"] = float(np.mean(r["latencies_ms"]))
        r["lat_std"] = float(np.std(r["latencies_ms"]))
        r["conf_mean"] = float(np.mean(r["confidences"]))

    m = models[0]
    b = models[1] if len(models) > 1 else m
    print(f"\n  {'Tool retrieval accuracy':<40s} {all_results[m]['tool_acc_pct']:>18.0f}% {all_results[b]['tool_acc_pct']:>20.0f}%")
    print(f"  {'Chat necessity accuracy':<40s} {all_results[m]['chat_acc_pct']:>18.0f}% {all_results[b]['chat_acc_pct']:>20.0f}%")
    print(f"  {'Avg embedding latency (ms)':<40s} {all_results[m]['lat_mean']:>18.1f} {all_results[b]['lat_mean']:>20.1f}")
    print(f"  {'Latency std (ms)':<40s} {all_results[m]['lat_std']:>18.1f} {all_results[b]['lat_std']:>20.1f}")
    print(f"  {'Avg confidence score':<40s} {all_results[m]['conf_mean']:>18.3f} {all_results[b]['conf_mean']:>20.3f}")
    print(f"  {'Path1 / Path2 / NoTool':<40s} {all_results[m]['path1']:>3d}/{all_results[m]['path2']:>2d}/{all_results[m]['no_tool']:>2d}"
          f"           {all_results[b]['path1']:>3d}/{all_results[b]['path2']:>2d}/{all_results[b]['no_tool']:>2d}")

    # Per-query side-by-side
    print(f"\n{sep}")
    print("  PER-QUERY DETAIL")
    print(f"{sep}")
    print(f"  {'Query':<28s} {'MiniLM path':<12s} {'conf':>6s} {'BGE path':<12s} {'conf':>6s} {'Match':>6s}")
    print(f"  {'-'*28} {'-'*12} {'-'*6} {'-'*12} {'-'*6} {'-'*6}")
    for i, q in enumerate(all_results[m]["queries"]):
        qb = all_results[b]["queries"][i]
        path_m = q["path"]
        path_b = qb["path"]
        conf_m = q["confidence"]
        conf_b = qb["confidence"]
        af_m = q["all_found"]
        af_b = qb["all_found"]
        match = "Both" if af_m == af_b else ("MiniLM" if af_m else "BGE" if af_b else "Neither")
        label_q = q["label"] + ":"
        print(f"  {label_q:<28s} {path_m:<12s} {conf_m:>5.3f} {path_b:<12s} {conf_b:>5.3f} {match:>6s}")

    # Recommendation
    print(f"\n{sep}")
    print("  RECOMMENDATION")
    print(f"{sep}")
    m_acc = all_results[m]["tool_acc_pct"]
    b_acc = all_results[b]["tool_acc_pct"]
    m_chat = all_results[m]["chat_acc_pct"]
    b_chat = all_results[b]["chat_acc_pct"]
    m_lat = all_results[m]["lat_mean"]
    b_lat = all_results[b]["lat_mean"]

    if b_acc >= m_acc and b_lat <= m_lat * 1.3:
        print("  -> BGE-small-en-v1.5 recommended (as good/better accuracy, lighter model)")
    elif b_acc >= m_acc - 10 and b_lat <= m_lat:
        print("  -> BGE-small-en-v1.5 viable alternative (comparable accuracy, faster)")
    elif b_lat > m_lat * 1.5:
        print(f"  -> Stick with all-MiniLM-L6-v2 (BGE is {b_lat/m_lat:.1f}x slower)")
    elif b_lat < m_lat:
        print("  -> BGE-small-en-v1.5 recommended (faster latency, competitive accuracy)")
    else:
        if b_acc > m_acc:
            print(f"  -> BGE-small-en-v1.5 recommended ({b_acc-m_acc:.0f}% better tool accuracy)")
        elif m_acc > b_acc:
            print(f"  -> Stick with all-MiniLM-L6-v2 ({m_acc-b_acc:.0f}% better tool accuracy)")
        else:
            print("  -> Tie. BGE-small-en-v1.5 preferred for disk savings (33MB vs 80MB)")

    print(f"    Tool accuracy:       MiniLM={m_acc:.0f}%  BGE={b_acc:.0f}%")
    print(f"    Chat gate accuracy:  MiniLM={m_chat:.0f}%  BGE={b_chat:.0f}%")
    print(f"    Avg latency:         MiniLM={m_lat:.0f}ms  BGE={b_lat:.0f}ms")
    print("    Disk size:           MiniLM=80MB  BGE=33MB")
    print(f"{sep}")


if __name__ == "__main__":
    all_results = {}
    for m in ["all-MiniLM-L6-v2", "BAAI/bge-small-en-v1.5"]:
        all_results[m] = test_model(m)
    print_comparison(all_results)
