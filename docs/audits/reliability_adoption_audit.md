# Nexus AI — Reliability Adoption / Coverage Audit

Date: 2026-08-17 · Method: scoped ripgrep per subsystem, every swallow site manually verified · Read-only

Scope: 13 subsystem directories (mcp, hive, memory, plugins, queue, providers, tools/nexus_tools, gateway, sandbox, evolution, skills, reasoning, intelligence).

## Summary table

| Subsystem | Verdict | Imports reliability | Silent swallows | Strongest evidence |
|---|---|---|---|---|
| mcp/ | unwired | none | 0 | `mcp/client/scripts/client.py:316-321` — own breaker, half-open retry |
| hive/ | partial | `providers.reliability` ×1 | 2 | `hive/engine.py:24` redact_secrets only; `:237` own "quarantine the uncertain operation" |
| memory/ | partial | `providers.reliability` ×1 | 6 | `memory/__init__.py:37` redact_secrets only; `:505-506` `except Exception: pass` on persistence |
| plugins/ | unwired | none | 1 | `plugins/manager.py:685-686` `except Exception: pass`; init failures log-and-disable |
| queue/ | partial | `providers.reliability` ×1 | 7 | `queue/driver.py:129-135` homegrown per-worker quarantine |
| providers/ | partial (origin) | in-package ×6 | 14 | `providers/reliability.py:75` own 12-class `FailureClass` (dual taxonomy) |
| tools/nexus_tools/ | unwired | none | 9 | `tools/nexus_tools/result.py:86-100` `classify_error` duplicates envelope classification |
| gateway/ | partial | ×4 | 28 | `gateway/base.py:95-138` own backoff poll loop; `delivery.py:134` own `max_attempts=8` |
| sandbox/ | unwired | none | 1 | `sandbox/sandbox_manager.py:529-534` string-coded `[SANDBOX_TIMEOUT]`/`[EXECUTION_ERROR]` |
| evolution/ | unwired | none | 2 | `evolution/quality.py:104-130` provider-failure awareness is text markers only |
| skills/ | unwired | none | 32 | `skills/engine.py:67,325` own `max_retries` metadata; `_common.py:418` own `_sleep_backoff` |
| reasoning/ | unwired | none | 1 | `reasoning/hyper_engine.py:205-208` catch → `self.last_error` string → degrade |
| intelligence/ | partial | ×2 | 1 | `intelligence/moe_router.py:9,347,359` `classify_failure` recorded, never enveloped |

Totals: 104 silent-swallow sites (49 × `except Exception: pass`), zero bare `except: pass` anywhere.

Top offenders: `skills/engine.py` (9), `memory/__init__.py` (6), `queue/driver.py` (4), `tools/nexus_tools/result.py` (4), `gateway/platforms/telegram.py` (4).

## Key findings

1. **Only `orchestrators/v5/` consumes `reliability.*`.** 7 of 13 subsystems have no reliability awareness at all (mcp, plugins, tools/nexus_tools, sandbox, evolution, skills, reasoning).
2. **`providers/reliability.py` remains the shared transport layer** (redaction, classification, circuit breakers, `call_with_reliability`); the new package wraps its `classify_failure` and adds envelope/recovery/goal/state semantics on top. The dual `FailureClass` taxonomies (12 vs 30 classes) are the main duplication; `reliability/failure.py` maps provider names to its own taxonomy at classification time.
3. **`tools/nexus_tools/result.py::classify_error` is the clearest contract duplication** — a parallel `{type, message, retryable}` taxonomy that should eventually be replaced by `envelope_from_exception`.
4. **Confirmed independent implementations (by design, still unwired):** `queue/driver.py` worker quarantine/replacement and `tools/web_search/scripts/web_search.py` bounded retry — both validated by their own test suites; envelope wiring there is a follow-up, not a defect.
5. The "partial" group (hive, memory, queue, gateway, intelligence) uses `redact_secrets`/`classify_failure`/`bounded_tool_retry` helpers and re-implements retry/backoff/breaker/quarantine locally — reasonable for now, but each is a candidate for `RecoveryEngine` adapters later.

## Recommended next wave (not done in this mission)

- Envelope adapter for `tools/nexus_tools` (replace `classify_error`), `mcp`, `hive`, `memory`.
- Persist worker quarantine (`queue/driver.py`) so it survives restart.
- Route the 104 swallow sites: log-with-context or envelope, never silent.
- Unify the two `FailureClass` taxonomies (map once, in one place).