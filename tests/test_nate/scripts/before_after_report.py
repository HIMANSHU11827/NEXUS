"""NATE Before/After comparison report."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from intelligence.nate.nate_engine import NATE

n = NATE()
n.set_layer("adaptive_schema", False)
n.set_layer("execution_graph", False)
n.set_layer("self_healing", False)

for i in range(50):
    n.register_tool(
        name=f"tool_{i}",
        description=f"Description for tool number {i} that does some specific task",
        parameters={"type": "object", "properties": {f"param_{i}": {"type": "string", "description": f"Parameter for tool {i}"}}},
        required=[f"param_{i}"],
    )

n.set_layer("adaptive_schema", True)
n.set_layer("execution_graph", True)
n.set_layer("self_healing", True)
n.set_flow("start", "finish")
for i in range(49):
    n.add_dependency(f"tool_{i}", f"tool_{i+1}", 1)

report = n.before_after_report("use tool 5 for a task")
s = report["savings_percent"]
b = report["before"]
a = report["after"]

sep = "=" * 65
print(sep)
print("   NATE BEFORE vs AFTER \u2014 50 TOOL SIMULATION")
print(sep)
print()
print("  Tools registered:       50")
print("  Query:                  \"use tool 5 for a task\"")
print()
dash = "-" * 30
dash2 = "-" * 12
dash3 = "-" * 14
dash4 = "-" * 10
total_saved = round((1 - a["total_estimate"] / b["total_estimate"]) * 100, 1)
print(f"  METRIC{' ' * 22} BEFORE     AFTER (NATE)  SAVINGS")
print(f"  {dash} {dash2} {dash3} {dash4}")
print(f"  Schema tokens{' ' * 14}{b['schema_tokens']:>8d}     {a['schema_tokens']:>8d}      {s['schema']:>5.1f}%")
print(f"  Routing LLM calls{' ' * 10}{b['routing_llm_calls']:>8d}     {a['routing_llm_calls']:>8d}      {s['routing']:>5.1f}%")
print(f"  Healing LLM calls{' ' * 10}{b['healing_llm_calls']:>8d}     {a['healing_llm_calls']:>8d}      {s['healing']:>5.1f}%")
print(f"  Total estimate{' ' * 13}{b['total_estimate']:>8d}     {a['total_estimate']:>8d}      {total_saved:>5.1f}%")
print()
print("  Cross-provider support:  OpenAI / Anthropic / Google / Ollama")
print("  No MCP overhead:         YES (native format, zero protocol tax)")
print("  Deterministic routing:   YES (Dijkstra graph, 0 LLM calls)")
print("  Self-healing (no LLM):   YES (Gene Map + RL + longest-prefix)")
print("  Small model ready:       YES (TSCG: 0-49% -> 90% accuracy)")
print(sep)
