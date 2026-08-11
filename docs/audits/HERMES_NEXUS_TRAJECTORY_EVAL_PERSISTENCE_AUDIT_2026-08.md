# Hermes vs Nexus: trajectory, evaluation, replay, and checkpoint persistence audit

Date: 2026-08-10
Hermes reference: `external/hermes-agent` at commit `03fa32c92dd445eb64c7f67434dd91d32c40701d`
Scope: read-only audit; `orchestrators/v5/core.py` was not edited.

## Executive finding

Hermes separates three durable concerns:

1. ShareGPT-compatible trajectories for training/debugging.
2. A SQLite verification-evidence ledger whose latest passing event is invalidated when the workspace is edited.
3. Git-backed checkpoints whose commit hashes and project identity make rollback references resolvable.

Nexus has stronger bounded run-evidence aggregation and a deterministic replay benchmark, but its persistence layers are less linked. `learning.py` writes a compact replay summary, `checkpoint.py` writes a phase snapshot, and `run_evidence.py` records paths and event IDs. These records are not currently guaranteed to resolve to one another or to existing artifacts.

The highest-value audit result is therefore not a new loop change: it is a persistence-contract test suite that distinguishes `present`, `missing`, and `unverified` artifacts and prevents redacted evidence from being mistaken for replayable source data.

## Field comparison

| Concern | Hermes persisted fields | Nexus persisted fields | Audit result |
|---|---|---|---|
| Trajectory identity | `timestamp`, `model`, `completed`, `conversations`; batch adds `prompt_index`, `metadata`, `partial`, `api_calls`, `toolsets_used`, `tool_stats`, `tool_error_counts` | `build_hermes_trajectory()` emits `timestamp`, `model`, `completed`, `conversations`; `run_evidence.py` stores only bounded trajectory counts/role counts/tool-call IDs | Nexus adapter is format-compatible, but not a durable trajectory writer and does not link the trajectory to a run/evidence ID. |
| Conversation/tool identity | ShareGPT `from`/`value`; tool calls and responses carry `tool_call_id` in normalized content | `turn_id`/`session_id` in replay; tool-call IDs only in trajectory summary; replay writer does not persist the action list or call IDs | Nexus replay is an evaluation summary, not a complete replay transcript. |
| Verifier identity | SQLite `verification_events.id`, `session_id`, resolved `cwd`/`root`, command, canonical command, kind, scope, status, exit code, output summary | `verification` summary copies selected verdict fields; canonical event IDs can be summarized in run evidence | Hermes has a durable verifier record and state pointer; Nexus has a bounded projection without a stable verifier-artifact reference. |
| Verification freshness | `verification_state.last_event_id`, `last_edit_at`, `changed_paths_json`; edits make prior evidence `stale` | No equivalent freshness contract in `run_evidence.py`; a path or verdict can remain present after its underlying artifact changes | Missing Nexus stale/unverified semantics. |
| Replay linkage | Hermes session replay code preserves provider-facing message fields and tool-call identity; trajectory is self-contained | `replays.jsonl` entry has timestamp, turn/session IDs, input/response previews, success, action/failure counts, plan steps | Nexus has no generated replay entry ID/digest and no guaranteed link from evidence to the exact JSONL line. |
| Checkpoint identity | Git commit hash/short hash, timestamp, reason, project hash/ref; restore operates on a validated commit | JSON checkpoint has `turn_id`, `phase`, `ts`, `session`, context/plan/actions/mental state/recent messages, and a filesystem `file` only after load | Nexus checkpoint can be located by filename, but has no content digest, parent, verifier linkage, or explicit missing-artifact state. |
| Artifact resolution | Hermes resolves project roots and validates checkpoint commit/path operations; verification state is read from its DB | Nexus stores `replay_path`/`checkpoint_paths` as bounded strings and writes them without checking existence | Direct gap: evidence can say a trace was logged while its path is absent. |
| Redaction | Hermes has `agent.redact` utilities and applies redaction in selected dump/diagnostic paths; trajectory save itself is not a universal redaction boundary | `run_evidence.py` recursively redacts; `learning.py` and checkpoint JSON serialization write user/context/action/message fields directly | Nexus evidence is redacted, but replay/checkpoint persistence needs independent redaction tests. |
| Missing artifacts | Hermes verification returns `unverified` when there is no state and `stale` after edits; checkpoint APIs return no-checkpoint/errors conservatively | `V5Bench.load()` returns an empty list for a missing replay, making missing and empty indistinguishable in aggregate stats | Nexus benchmark/evidence consumers need explicit `missing` versus `empty` status. |

## Verifier, replay, and checkpoint linkage map

### Hermes

The verifier path is:

`command result -> VerificationEvidence -> verification_events row -> verification_state.last_event_id -> verification_status()`

The important linkage fields are:

- `id`: durable verifier-event identity.
- `session_id` and resolved `root`: lookup scope.
- `cwd`: execution location.
- `canonical_command`, `kind`, `scope`: what was actually verified.
- `status`, `exit_code`, `output_summary`, `created_at`: verdict evidence.
- `last_edit_at` and `changed_paths_json`: freshness invalidation.

The trajectory path is separate:

`messages -> normalized ShareGPT conversations -> JSONL entry`

It preserves tool identity in the serialized conversation, but the base trajectory envelope does not contain a verifier-event ID or checkpoint reference. Batch output adds operational statistics, not verifier linkage.

The checkpoint path is Git-backed:

`working directory -> project hash/ref -> Git commit -> list/diff/restore`

The commit hash is the resolvable artifact identity; the working directory and project hash prevent using a checkpoint from the wrong project.

### Nexus

The current paths are:

`turn result -> learning._log_turn_replay() -> .nexus_v5/replays.jsonl`

`phase transition -> checkpoint._checkpoint_save() -> .nexus_v5/checkpoints/<turn>_<phase>.json`

`terminal result -> run_evidence.build_run_evidence() -> workspace/provider_run_evidence/<provider>/<model>/<turn>.json`

The run-evidence trace projection contains:

- `trace.canonical_event_ids` and bounded `trace.canonical_events`.
- `trace.replay.path`, `trace.replay.logged`, and optional `trace.replay.entry_id`.
- Compatibility alias `trace.replay_path`.
- `trace.checkpoint_paths`.
- Bounded verifier fields such as `success`, `evidence_ok`, `verified`, action counts, verifier name/reason, and anomalies.

The implementation does not currently prove that:

- `trace.replay.path` exists or contains the matching `turn_id`/`session_id`.
- `trace.replay.entry_id` identifies a real JSONL record.
- each checkpoint path exists, parses, and contains the same turn/session identity.
- a verifier verdict is backed by a still-present artifact.
- replay/checkpoint content is redacted before persistence.

## Concrete gaps and severity

### P0: unresolved evidence paths can look valid

`run_evidence._trace_summary()` normalizes path strings but does not inspect the filesystem. A consumer cannot distinguish a logged replay from a planned replay path, or a retained checkpoint from a pruned/deleted checkpoint.

### P1: no stable replay record identity

`learning._log_turn_replay()` writes `turn_id` and `session_id`, but no record ID or digest. If the same turn is appended twice, evidence cannot identify which line it refers to. The optional `entry_id` accepted by `run_evidence.py` is not generated by the replay writer.

### P1: replay is summary-only

The writer records counts and previews, while `V5Bench` can score richer `actions` data when supplied. This creates a silent coverage gap: a successful replay with missing actions may pass the current permissive schema path, and the original tool-call sequence is not reconstructable from the persisted line.

### P1: checkpoints lack provenance and content identity

Nexus checkpoints contain useful state but not a content digest, parent checkpoint, provider/model, verifier event, replay entry, or provider-run-evidence path. A filename is not sufficient to prove that a checkpoint belongs to the evidence bundle being inspected.

### P1: redaction is not uniform across persistence layers

`run_evidence.py` redacts recursively, but `learning.py` and `checkpoint.py` serialize free-form input/context/actions/messages with `json.dumps(..., default=str)`. These paths need their own secret-leak tests even if the final evidence bundle is safe.

### P2: missing replay is conflated with empty replay

`V5Bench.load()` returns `[]` for a nonexistent replay file. This is safe operationally but weak for audit reporting and can produce a misleading `0/0` result.

## Proposed tests (no implementation implied)

The following tests should be added without changing `core.py`. They can target `orchestrators/v5/run_evidence.py`, `learning.py`, `checkpoint.py`, and `bench.py` directly.

### 1. Resolvable replay path and matching identity

`test_run_evidence_reports_replay_path_status_and_matching_entry`

Arrange a temporary `.nexus_v5/replays.jsonl` containing one JSON object with `turn_id="turn-7"`, `session_id="session-2"`, and a deterministic record ID/digest if the writer supports it. Build evidence pointing at that file.

Assert:

- the stored path resolves under the test root;
- status is `present` rather than merely `logged`;
- the file contains a record matching both turn and session IDs;
- an entry identity, when present, resolves to exactly one line;
- a mismatched session or turn is reported as `unlinked`, not `present`.

### 2. Resolvable checkpoint paths

`test_run_evidence_reports_checkpoint_presence_and_identity`

Write a checkpoint JSON with `turn_id="turn-7"`, `phase="act"`, and `session="session-2"`, then build evidence with that path.

Assert:

- the path exists and is a regular file;
- JSON is parseable;
- turn/session identity matches the evidence;
- a directory, malformed JSON, or wrong-turn checkpoint is classified as `invalid` or `unlinked`;
- no path outside the workspace is accepted as a valid project artifact unless explicitly allowed by the contract.

### 3. Missing artifacts are explicit

`test_missing_replay_and_checkpoint_are_not_reported_as_logged`

Build evidence with nonexistent replay/checkpoint paths and run the benchmark against a missing replay file.

Assert:

- evidence reports `missing` for each absent artifact;
- `replay.logged` does not imply `replay.status == "present"`;
- benchmark output distinguishes `missing` from an existing but empty file;
- a missing artifact does not produce a passing verifier/replay linkage.

### 4. Replay content is redacted at the persistence boundary

`test_learning_replay_does_not_persist_secrets`

Feed `_log_turn_replay()` input and response previews containing `Bearer ...`, `sk-...`, URL `api_key=...`, and password-like values.

Assert the JSONL bytes contain no raw secret values and remain valid JSON. Also verify that the redacted preview remains bounded.

### 5. Checkpoint content is redacted at the persistence boundary

`test_checkpoint_snapshot_redacts_context_actions_and_recent_messages`

Populate runtime context, actions, mental state, and recent messages with the same secret corpus, save a checkpoint, and inspect the raw JSON.

Assert no secret survives in any nested field, while `turn_id`, `phase`, `session`, and resume behavior remain intact.

### 6. Verifier freshness and missing verifier artifact

`test_verifier_linkage_is_stale_after_artifact_edit_or_missing_evidence`

Create a passing verifier artifact, link it to evidence, then mutate or remove the artifact.

Assert the consumer returns `stale`/`missing` rather than `passed`. Separately test a missing verifier record as `unverified`, matching Hermes semantics.

### 7. Replay determinism and duplicate detection

`test_replay_entry_identity_detects_duplicate_turn_records`

Append two records with the same `turn_id` and `session_id` but different content.

Assert the linkage result is `ambiguous` and the benchmark does not silently select one. Re-running evaluation over an unchanged file must remain deterministic.

### 8. Redacted evidence does not masquerade as executable replay

`test_run_evidence_trajectory_projection_is_not_replayable`

Build evidence containing a long tool result and verify that the bounded trajectory projection contains counts/IDs only, while the report explicitly marks it as a summary. This prevents downstream code from treating `run_evidence.json` as a complete training trajectory.

## Recommended contract for a future persistence upgrade

Without prescribing an implementation in this audit, a resolvable Nexus evidence record should eventually expose:

```json
{
  "artifact_status": "present|missing|invalid|unlinked|ambiguous",
  "replay": {
    "path": "...",
    "entry_id": "...",
    "sha256": "...",
    "turn_id": "...",
    "session_id": "..."
  },
  "checkpoints": [
    {
      "path": "...",
      "sha256": "...",
      "turn_id": "...",
      "phase": "...",
      "session_id": "..."
    }
  ],
  "verification": {
    "status": "passed|failed|stale|unverified|missing",
    "artifact_id": "..."
  }
}
```

The important invariant is that a positive verdict requires a resolvable artifact and matching identity; a path string or boolean `logged` flag alone is insufficient.

## Evidence inspected

- Hermes: `agent/trajectory.py`, `agent/agent_runtime_helpers.py`, `agent/verification_evidence.py`, `agent/verify/runner.py`, `tools/checkpoint_manager.py`, `batch_runner.py`, trajectory-format documentation, and related tests.
- Nexus: `orchestrators/v5/learning.py`, `orchestrators/v5/checkpoint.py`, `orchestrators/v5/bench.py`, `orchestrators/v5/run_evidence.py`, existing V5 replay/evidence/checkpoint tests.
- No source file was edited by this audit, and `orchestrators/v5/core.py` was not modified.
