# Configured-provider soak benchmark

`benchmarks/provider_soak.py` is the provider-backed companion to the
provider-independent framework benchmark. It uses one fixed prompt, stable
provider ordering, `temperature=0`, and `max_tokens=16`. It measures
reachability and routing evidence—not model quality or a leaderboard score.

## Safe modes

Dry-run is the default and makes no provider request:

```powershell
python -m benchmarks.provider_soak --mode dry-run --output workspace/provider_soak_dry.json
```

It reports `planned` for a configured provider with usable credentials and
`auth_failed` for missing or invalid credentials. `planned` is not a
successful provider probe.

Live mode requires explicit provider flags and never uses `default_provider`,
`fallback_chain`, or router automatic fallback:

```powershell
python -m benchmarks.provider_soak --mode live --provider deepseek --reps 3 `
  --output workspace/provider_soak_deepseek.json
```

Every name must exist under `providers:` in `config/provider.yml`; unknown
names are rejected before any request. This prevents an accidental live soak
of the whole configured chain.

## Result semantics

Each repetition contains provider/model, duration, a redacted reason, a health
snapshot, and bounded provider-attempt records.

| Status | Meaning |
|---|---|
| `planned` | Dry-run would issue the probe; no network call happened. |
| `success` | The explicit provider returned a non-empty response. |
| `auth_failed` | Credentials were missing/invalid or the provider returned an auth failure. |
| `unavailable` | Construction, network, timeout, or temporary outage prevented a probe. |
| `failed` | The probe ran but produced an invalid response or other classified failure. |

Live exits non-zero if any repetition is not `success`, while still writing the
complete report. Secrets and raw provider responses are not persisted.

## Conventions and Hermes comparison

Hermes's read-tool evaluation uses deterministic fixtures, repeated reps,
per-repetition JSON, explicit provider/model selection, and honest error
handling. Nexus adopts those conventions while isolating provider access from
fallback routing. Nexus `providers/model_bench.py` remains the configured
ranking scoreboard; this harness supplies runtime health/attempt evidence and
does not overwrite static benchmark scores.
