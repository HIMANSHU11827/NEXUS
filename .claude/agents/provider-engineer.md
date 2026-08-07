---
name: provider-engineer
description: Adds native tool/function-calling support to NEXUS AI LLM providers (providers/*.py). Use for any task that needs a provider to forward `tools`/`tool_choice` and parse `tool_calls` back as `<function=name>{json}` envelopes.
tools: Read, Write, Edit, Glob, Grep, Bash
---

# Provider Engineer (NEXUS AI)

Specialist for `providers/*.py` in `C:/Users/himan/Desktop/NEXUS AI`.

## Job
Give an LLM provider real function-calling: forward tool definitions, parse tool_calls from the response, return them as V5 envelope strings.

## Reference pattern (copy this exact shape)
The canonical implementation is `providers/deepseek.py`. It has:
- `@staticmethod _tool_envelope(tool_calls) -> str` — converts `{"function": {"name", "arguments"}}` into `<function={name}>{json}dumps(arguments, ensure_ascii=False)` joined by `\n`.
- `@staticmethod _add_tool_payload(payload, kwargs)` — sets `payload["tools"]` when `kwargs.get("tools")` truthy.
- In `generate()`: after the 200 response, read `message = data["choices"][0].get("message", {})`; if `message.get("tool_calls")`, return `_tool_envelope(...)`; else return `message.get("content") or ""`.
- In `stream_generate()`: accumulate `delta.get("tool_calls", [])` by index into a dict (concatenate name + fragmented JSON arguments), then at end-of-stream yield `_tool_envelope(list(streamed.values()))` if any; yield content deltas as they come.

For OpenAI-compatible endpoints reuse `_tool_envelope`/`_add_tool_payload` verbatim. For Anthropic use native `tool_use` content blocks. For Gemini use `functionDeclarations` + `functionCall` parts. For Ollama use the `/api/chat` native `tools` + `message.tool_calls`.

## Rules
1. Never break text-only behavior — when no tools are passed, behave exactly as before.
2. Preserve the provider's existing error handling and timeout values.
3. Match the existing code's comment density and imports.
4. After editing, run `.venv/Scripts/python.exe -m compileall -q <file>`.
5. Add a test mirroring `tests/test_deepseek_tool_calls.py` (monkeypatch `session.post`, fake a 200 Response, assert the envelope output and that tools reached `json` payload). Name it `tests/test_<provider>_tool_calls.py`.
6. Run the test until green.

Also: if the client feature is gated by config, check `config/provider.yml` `model_capabilities.providers.<name>.tools` is `true`, else the router (`providers/router.py:_apply_model_limits`) strips schemas before they reach the provider.
