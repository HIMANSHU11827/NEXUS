# NEXUS AI — Runtime Flow Map

> Companion to `NEXUS_CODEBASE_MAP.md` (structure). This documents how a message
> actually flows through the running system, from input to answer. Verified
> against source on 2026-08-05.

## 1. Entry Points

| Surface | Command | Entry |
|---|---|---|
| TUI | `python -m nexus` | Ink (React 19) → backend → `NexusLoop` |
| GUI | `python -m nexus --gui` | React18/Vite → FastAPI `gui/api.py` → `NexusLoop` |
| Server API | `python -m nexus --server` | FastAPI `server/__init__.py` (:8000) → `NexusLoop` |
| Gateway | `python -m nexus --gateway` | `gateway/run.py` → `NexusLoop` |
| Setup | `python -m nexus --setup` | `tui/setup_wizard.py` |

All surfaces converge on the same canonical loop.

## 2. The Agent Loop (canonical path)

`orchestrators/v5/core.py` — `NexusLoop`.

```
user message
  └─ run() / stream_run()  ──┐
       _turn_events (core.py:1731)
         └─ _run_direct_model_tool_loop (core.py:1956)   ← LIVE PATH
              └─ direct_loop.py
```

### direct_loop.py — the live model/tool loop

1. **Context build** — `_get_direct_tool_schemas()` (direct_loop.py:110-159) builds
   real `{"type":"function"}` schemas from the tool registry (skips `skill` category).
   `model_kwargs["tools"] = schemas; tool_choice="auto"` (:336-338).
2. **Model call** — `raw = await _safe_model_call_raw(messages, **kwargs)` (:340)
   → `model.py:_call_model_raw` (:135) → `brain.generate(**request)` (:157).
   `brain` = kernel MoE router (`core.py:388`).
3. **Brain dispatch** — `intelligence/moe_router.py` → `provider.stream_generate(messages, **call_kwargs)`.
   Tool defs reach the LLM API only if the provider forwards them (see §5).
4. **Parse** — `_model_turn_parts(raw)` (:597-639):
   - native `tool_calls` → `_part_tool_calls` (:651)
   - text envelopes `<function=name>{json}` → (:612-623)
   - `parse_all_tool_calls` from `tools/nexus_tools/call_parser.py` (:628-638)
5. **Execute** — `_run_tool(call)` (:453) → `tools.py:_run_tool` (:54-225):
   - command aliases → risk score → permission → `sandbox.stream_execute`
   - registry tools → `ToolRegistry.stream_execute` → `entry.instance.execute(params)`
6. **Loop / verify** — results appended as `role:"tool"` messages (:475-477);
   failures → REPAIR system message (:494-504); bounded by
   `direct_loop_max_rounds=8` (:15); truthful verdict via `_verification_payload` (:31).
7. **Emit** — final text as a `content` event (core.py:1997).

Dead code (confirmed unreachable): PAORR block after `return` at core.py:2023,
`_v1_compat_turn` (:1405-1530), `_verify_all_parallel` stub (:965-966).

## 3. Provider routing

```
model.py → brain.generate (NexusMoERouter, intelligence/moe_router.py:299)
         → provider.stream_generate(messages, **call_kwargs)   (moe_router.py:215-219)
         → factory.get_provider_by_name(...)                   (providers/factory.py:202)
```

The MoE router calls the raw provider directly. `providers/router.py` (with its
capability-based tool stripping) is NOT in this path.

## 4. Memory write path (after-turn)

`core.py:2142-2149` → `memory/__init__.py:sync_all(task_desc, response)` fans to:
- `_sync_session` (session transcript)
- `_sync_opencode_memory` (learned.md)
- MemoryForge (`evolution/memory_forge`)

**Verification gate (P0):** Historically unverified model text reached all three.
A per-action verifier (`orchestrators/v5/verification.py`) exists but was not fed
into the memory path. Fix in flight to gate memory on verified evidence.

## 5. Tool support by provider (2026-08-05)

| Provider | Tools | Notes |
|---|---|---|
| deepseek | ✅ | reference impl (`_add_tool_payload` + `_tool_envelope`) |
| openrouter | ✅ | |
| openai | ✅ (fixed) | was dropping tools |
| anthropic | ✅ (fixed) | native tool_use blocks |
| universal | ✅ (fixed) | was returning only content |
| azure_openai | ✅ (fixed) | was broken (empty endpoint) |
| gemini | ✅ (fixed) | functionDeclarations |
| groq/mistral/qwen/xai/fireworks/together/sambanova/nvidia/commandcode/vlm | in progress | OpenAI-compat batch |
| ollama/llama_cpp/cohere | in progress | native formats |
| huggingface/replicate/perplexity | low priority | no native tool API |

Config gate: `config/provider.yml` `model_capabilities.providers.<id>.tools`
controls `providers/router.py:_apply_model_limits` stripping (only when the router
is used). Enabled for all tool-capable providers 2026-08-05.

## 6. Key subsystems

- **Kernel** (`kernel/__init__.py`) — thread-safe singleton, lazy-loaded subsystems;
  `moe` → `NexusMoERouter`; `tools` → `ToolRegistry`.
- **Tools** (`tools/nexus_tools/registry.py`) — `.jsnol` metadata discovery,
  `stream_execute` → `entry.instance.execute`.
- **Sandbox** (`sandbox/`) — 3-tier, risk scoring, failure memory.
- **Permission** (`permissions/`) — deny→allow precedence, AUTO_PILOT.
- **Memory** (`memory/`) — multi-source MemoryManager.
- **RAG** (`rag/`) — BM25 + SimHash hybrid; atlas deep index.
- **Gateway** (`gateway/platforms/`) — async adapters per platform.
- **Hive** (`hive/`) — sub-agent engine.