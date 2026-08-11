# Hermes ↔ Nexus runtime comparison

Date: 2026-08-10
Hermes source: `external/hermes-agent`, NousResearch, commit
`03fa32c92dd445eb64c7f67434dd91b32c40701d`.

This is an implementation comparison, not a claim that either framework is
universally better. Hermes is a useful reference for explicit runtime
contracts; Nexus remains the local-first system of record.

## Token and iteration model

Hermes uses `agent/iteration_budget.py` with a thread-safe
`IterationBudget.consume()` / `refund()` counter. The parent and each
subagent receive independent caps. Its `agent/conversation_loop.py` also
tracks normalized input, output, cache, and reasoning buckets, performs rough
preflight estimates, and compacts before an API request.

Nexus had per-run `max_turns`, cost, and token fields in
`orchestrators/v5/control.py`, plus model-specific context/output caps in
`providers/model_capabilities.py`, but the direct V5 tool loop did not feed
actual provider usage into `_budget_tick()`. This pass adds
`orchestrators/v5/token_usage.py`, normalizes common response shapes, uses a
safe estimate when a provider reports no usage, and stops before a new request
when the existing run budget is exhausted.

## Loop model

Hermes centers the conversation loop around a long-lived agent object. Each
iteration does request-size estimation, optional context selection/compaction,
provider retries, credential rotation/fallback, tool dispatch, usage
accounting, and persistence. It has a large configurable iteration cap and a
separate subagent cap.

Nexus V5 separates these concerns across `direct_loop.py`, `model.py`,
`context_manager.py`, `control.py`, and `router.py`. Its strengths are strict
tool evidence, call/result-safe compaction, approval gates, durable queue/Hive
recovery, and a finalization turn. Its weakness was cross-module telemetry;
the new token-usage seam reduces that gap without coupling Nexus to Hermes'
transport code.

## Provider, credential, and fallback model

Hermes resolves providers through `hermes_cli/runtime_provider.py` and
`hermes_cli/providers.py`, supports explicit API modes, credential pools,
OAuth/setup tokens, retry classification, and a configured fallback chain
(`hermes_cli/fallback_config.py`). Its loop can rotate a credential, retry a
transient failure, switch provider/model, and preserve the last clean
transcript before continuing.

Nexus uses `providers/factory.py` + `providers/router.py` with per-provider
health, circuit breakers, capability-aware output clamping, retry/backoff,
OAuth refresh storage, and streaming fallback. Nexus is stronger on explicit
local safety boundaries and circuit state; Hermes is stronger on credential
pool rotation and fallback continuity inside one conversation. The next Nexus
slice should add a durable, redacted provider-attempt record and explicit
fallback reason to canonical events before changing routing behavior.

## Sandbox and non-sandbox operation

Nexus has a three-tier sandbox (`sandbox/`) and risk-scored command execution,
with normal workspace-scoped execution as the unattended default and approval
broker integration for sensitive operations. Hermes exposes multiple runtime
backends and tool guardrails, including container/browser/desktop integrations
and explicit tool approval paths. Nexus should retain its fail-closed local
policy and add parity tests proving every direct-loop tool path reaches the
risk scorer and approval broker.

## Prioritized upgrade backlog

1. Add provider-attempt telemetry with redacted error classification and
   fallback reason in canonical events. The first implementation now records
   a bounded in-memory attempt history in `providers/attempts.py`, exposes it
   through the active MoE router, and includes it in V5 terminal run payloads.
2. Add credential-pool style rotation for multiple configured credentials,
   with per-provider locking and fail-closed refresh behavior. Nexus now has
   single-flight OAuth refresh locks for async storage calls and synchronous
   factory resolution; multi-credential profile rotation remains separate.
3. Add direct-loop integration tests for budget accounting, max-token clamp,
   provider error redaction, and approval/sandbox routing.
4. Add durable trajectory artifacts containing request estimates, actual usage,
   compaction boundaries, tool evidence, fallback transitions, and verifier
   results.
5. Add a cross-provider soak benchmark using identical prompts, tool schemas,
   sandbox policy, and completion criteria.

## Safety correction from source review

Hermes guards programmatic code execution before spawning a subprocess. Nexus
had a latent exception path where code-action mode directly invoked Python if
the sandbox object was missing. That path now fails closed with
`code-action requires an active sandbox`, and the regression suite verifies no
unsandboxed execution occurs.

## Memory egress correction

Hermes sanitizes memory-provider context before it crosses into an LLM
request. Nexus already gates durable learning on verified tool evidence, but
its aggregate `MemoryContext` could contain secrets from legacy session,
failure, RAG, or knowledge sources. `MemoryContext.as_text()` now applies the
shared credential redactor at the final model-context boundary. Source
provenance and provider-backed memory plugins remain future work.
