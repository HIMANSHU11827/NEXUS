# NEXUS V5 Architecture Documentation

## Overview

NEXUS V5 is the next-generation self-adaptive quantum loop architecture that builds on V3's PAORR-Actor foundation with advanced self-adaptive capabilities, quantum-inspired optimization, and full autonomous evolution.

## Architecture Layers

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    NEXUS V5 - Self-Adaptive Quantum Loop                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Phase 0: Meta-Learning Layer (Self-Improving)                             │
│  Phase 1: Perception Layer (Multi-Modal Input)                             │
│  Phase 2: PAORR-Enhanced Loop (V3 + Enhancements)                          │
│  Phase 3: Quantum Actor Orchestration (V3 + Quantum)                       │
│  Phase 4: Self-Evolution (Autonomous Improvement)                          │
│  Phase 5: Emergent Behavior (Swarm Intelligence)                           │
│  Phase 6: Consciousness Layer (Self-Awareness)                              │
│  Phase 7: Output Layer (Multi-Modal Response)                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Module Structure

### Core Module: `core.py`
- **NexusLoopV5**: Main orchestrator class
- **V5LoopState**: Enum for loop lifecycle states
- **V5TurnContext**: Dataclass for per-turn context
- **V5Runtime**: Dataclass for overall runtime state

**Key Features:**
- Coordinates all V5 layers
- State machine management
- Event callbacks for state transitions
- Lazy-loaded layer initialization

### Layer 0: `meta.py`
- **MetaLearningLayer**: Learns how to learn
- **MetaLearningConfig**: Configuration for meta-learning
- **Experience**: Single experience for replay

**Key Features:**
- Hyperparameter optimization
- Architecture search
- Experience replay
- Strategy selection
- Learning rate adaptation

### Layer 1: `perceive.py`
- **PerceptionLayer**: Multi-modal input processing
- **PerceivedInput**: Result of perception processing
- **InputType**: Enum for input types (text, voice, vision, code)
- **Intent**: Enum for recognized intents

**Key Features:**
- Multi-modal input processing
- Intent recognition
- Context fusion
- Attention mechanism
- Entity extraction

### Layer 2: `paorr.py`
- **PAORREnhanced**: Enhanced PAORR loop implementation
- **Plan**: Complete plan with multiple steps
- **PlanStep**: Single step in a plan
- **ActionResult**: Result of action execution
- **Observation**: Multi-modal observation
- **Reflection**: Reflection on execution results

**Key Features:**
- Dynamic planning with hierarchical decomposition
- Alternative path generation
- Plan confidence scoring
- Parallel action orchestration
- Resource-aware scheduling
- Causal analysis and counterfactual reasoning
- Adaptive retry strategies

### Layer 3: `quantum.py`
- **QuantumActorModel**: Quantum-inspired actor model
- **QuantumActor**: A quantum-inspired actor
- **QuantumMessage**: Message between quantum actors
- **QuantumState**: Enum for quantum states

**Key Features:**
- Quantum-inspired superposition of states
- Entangled agent communication
- Quantum annealing for optimization
- Quantum parallelism
- Wavefunction collapse

### Layer 4: `self_evolution.py`
- **SelfEvolutionLayer**: Autonomous self-improvement
- **EvolutionCandidate**: A candidate improvement
- **EvolutionLog**: Log of evolution attempts
- **EvolutionPhase**: Enum for evolution phases

**Key Features:**
- Autonomous code generation
- Self-testing
- Self-deployment with rollback
- Continuous improvement
- Safe mode deployment

### Layer 5: `emergent.py`
- **EmergentBehaviorLayer**: Swarm intelligence
- **SwarmAgent**: A single agent in the swarm
- **ConsensusResult**: Result of consensus algorithm
- **SwarmTopology**: Enum for swarm topologies

**Key Features:**
- Swarm intelligence
- Consensus algorithms
- Self-organizing networks
- Stigmergy (indirect communication)
- Multiple topologies (full mesh, hub-and-spoke, ring, tree)

### Layer 6: `conscious.py`
- **ConsciousnessLayer**: Self-awareness and metacognition
- **SelfModel**: Model of self (capabilities, limits)
- **MentalState**: Current mental state
- **TheoryOfMindModel**: Model of other agents' mental states
- **ConsciousnessLevel**: Enum for consciousness levels

**Key Features:**
- Self-awareness (knows own capabilities and limits)
- Metacognition (monitors own cognitive processes)
- Theory of mind (understands other agents' mental states)
- Introspection (examines own internal state)
- Pattern recognition in performance

### Layer 7: `output.py`
- **OutputLayer**: Multi-modal output generation
- **OutputResult**: Result of output generation
- **OutputType**: Enum for output types

**Key Features:**
- Multi-modal output generation (text, voice, visuals, code)
- Explanation generation
- Confidence scoring
- Alternative suggestions

### Orchestrator: `orchestrator.py`
- **V5Orchestrator**: Integration layer with NEXUS infrastructure
- **create_v5_loop**: Factory function

**Key Features:**
- Integration with NEXUS kernel
- Memory integration
- Event emission
- Evolution logging
- Configuration management
- Runtime state monitoring

### Modular Mixins (V5)
V5 mixin modules composed into `NexusLoopV5` (see `core.py` class bases; MRO = 25 entries).

> **These are V5's own modules** — they are part of the V5 loop and the V5 architecture.
> They are **not** V1 modules and **not** ports of V1. Each module below is a V5
> component: it belongs to the V5 loop, is wired into `NexusLoopV5`, and is used
> by the V5 turn pipeline.

**Pipeline (the LOOP modules) — the turn engine:**
- `events.py` — V5EventEmitter (canonical events)
- `model.py` — V5ModelCaller (LLM calls)
- `tools.py` — V5ToolExecutor (real execution)
- `planning.py` — V5Planner (LLM plans)
- `response.py` — V5ResponseBuilder (final answers)
- `parallel.py` — V5ParallelExecutor
- `verification.py` — V5Verifier
- `retry.py` — V5RetryPolicy
- `learning.py` — V5Learning
- `control.py` — V5Control (abort/hooks)
- `log.py` — V5Logger (structured loop logging)
- `checkpoint.py` — V5Checkpoint (durable per-phase snapshots + resume)

**Subsystems:**
- `hive.py` — V5Hive
- `plugin.py` — V5Plugin
- `skill.py` — V5Skill
- `evolution.py` — V5Evolution
- `cron.py` — V5Cron
- `lifecycle.py` — V5Lifecycle
- `background_runner.py` — V5BackgroundRunner

**Security/config:**
- `config.py` — V5Config
- `permissions.py` — V5Permissions
- `sandbox.py` — V5Sandbox

#### How V5 uses its modules

**Pipeline (the LOOP modules) — the turn engine.** All called inside
`_turn_events()` (core.py:660), the 7-phase turn pipeline:
- `events.py` — `_emit_runtime_event` fires `run.started` at turn start (core.py:676); `_yield_pending_events` streams between every phase
- `model.py` — `_call_model`/`_stream_model`: the LLM access layer used by planning + response
- `planning.py` — `_llm_plan` generates the real plan in Phase 2 (PAORR)
- `tools.py` — `_run_tool` executes the plan's tools (Phase 2); this is where permissions/sandbox/verification/retry/learning hook in
- `parallel.py` — `_execute_parallel_tool_calls` runs independent tools in parallel (read-gather/write-sequential)
- `verification.py` — verifies tool evidence so success claims are grounded
- `retry.py` — `_enforce_tool_retry` retry ladder when a tool-requiring task plans no tools
- `learning.py` — `_collect_turn_signals` records failures/reflections in Phase 6.5 (core.py:760)
- `response.py` — `_generate_output` streams the final answer in Phase 7 (core.py:767)
- `control.py` — `_check_abort` between phases (core.py:712, 766); `abort()`; `_fire_post_tool_hooks` after tools
- `log.py` — `_log_stage`/`_log_tool`/`_log_runtime`/`_log_append`: every stage transition logs via `_transition_to` (core.py:909); JSONL audit trail at `.nexus/v5/v5_log.jsonl` (`_log_stats`, `_log_lines`)

**Subsystems — attached at specific loop points:**
- `hive.py` — `_inject_hive_context` in Phase 1 (core.py:706): spawns sub-agents for big tasks, injects `[HIVE_RESULT]`
- `skill.py` — `_inject_skill_context` + skills index in Phase 1 (core.py:702-705); `/skill-name` slash input → `_resolve_slash_skill`
- `plugin.py` — `_trigger_plugin_hooks` for pre/post-tool + `on_session_end` at session close
- `evolution.py` — `_handle_evolution_gaps` on tool failures; `_start_background_finalization` when run() finishes (core.py:579)
- `cron.py` — `_schedule_task` API: scheduled tasks run via a thread→async bridge
- `lifecycle.py` — `_lifecycle_mark` called by tools.py/skill.py/cron.py to track tool/skill state transitions
- `background_runner.py` — `_run_background` runs fire-and-forget work with retry/backoff; `submit_durable_background` adds SQLite lifecycle persistence and explicit factory-based startup rehydration

**Security/config — initialized at loop boot (core.py:289-295):**
- `config.py` — `_init_config()` loads config once at `__init__`, seeds runtime
- `permissions.py` — `_init_permissions()` maps policy→mode at boot; `_check_permission` is called by tools.py's audit before every tool call
- `sandbox.py` — `_init_security()` creates `CommandRiskScorer` + `SovereignSandbox` at boot; tools.py runs commands through `runtime.sandbox` with risk scoring + tier switching

## Key Innovations Over V3

### 1. Meta-Learning Layer
- Learns how to learn
- Hyperparameter optimization
- Architecture search
- Experience replay

### 2. Enhanced PAORR Loop
- Dynamic planning
- Hierarchical decomposition
- Alternative path generation
- Plan confidence scoring

### 3. Quantum-Inspired Actor Model
- Superposition of states
- Entangled communication
- Quantum annealing
- Quantum parallelism

### 4. Self-Evolution
- Autonomous code generation
- Self-testing
- Self-deployment
- Rollback capability

### 5. Emergent Behavior
- Swarm intelligence
- Consensus algorithms
- Self-organizing networks
- Stigmergy

### 6. Consciousness Layer
- Self-awareness
- Metacognition
- Theory of mind
- Introspection

## Expected Performance Improvements

- **30-40%** from meta-learning
- **20-30%** from quantum-inspired optimization
- **15-25%** from self-evolution
- **10-20%** from swarm intelligence
- **5-15%** from consciousness layer

**Total Expected Improvement: 80-130% over V3**

## Usage Example

```python
from orchestrators.v5 import create_v5_loop

# Create V5 loop with configuration
config = {
    "meta_learning_enabled": True,
    "quantum_mode": True,
    "consciousness_level": 7,
    "swarm_size": 10,
    "evolution_enabled": True
}

v5_loop = create_v5_loop(
    root_dir="/path/to/nexus",
    session_id="my_session",
    config=config
)

# Run V5 loop
result = await v5_loop.run(
    user_input="Write a function to sort an array",
    input_type="text"
)

print(result)
```

## Configuration Options

### Meta-Learning
- `meta_learning_enabled`: Enable/disable meta-learning (default: True)
- `learning_rate`: Learning rate for adaptation (default: 0.001)
- `experience_buffer_size`: Size of experience replay buffer (default: 1000)

### Quantum Mode
- `quantum_mode`: Enable quantum-inspired features (default: False)
- `entanglement_probability`: Probability of entanglement (default: 0.7)

### Consciousness
- `consciousness_level`: Level of consciousness (0-10, default: 1)
  - 0-3: Basic state tracking
  - 4-6: Self-awareness
  - 7-8: Metacognition
  - 9-10: Full consciousness with theory of mind

### Swarm
- `swarm_size`: Number of agents in swarm (default: 10)
- `swarm_topology`: Topology type (default: hub_and_spoke)

### Evolution
- `evolution_enabled`: Enable self-evolution (default: True)
- `safe_mode`: Only deploy with high confidence (default: True)

## Integration with NEXUS Subsystems

### Kernel Integration
- Lazy-loaded subsystem initialization
- Dependency injection
- Central singleton access

### Memory Integration
- Save V5 executions to memory
- Extract learnings for future use
- Experience replay

### Event Integration
- Emit V5 execution events
- State transition callbacks
- Real-time monitoring

### Evolution Integration
- Log V5 executions to evolution log
- Extract patterns and learnings
- Continuous improvement

### Tool Integration
- Meta tools pattern
- Tool-masking state machine
- KV-cache optimization
- V5 (verified): real tool execution with risk-scored commands (sandbox
  tier NORMAL), per-call permission AUDIT for registry tools (kernel plugin
  `pre_tool_call` hooks + policy check + human approval broker in ask-mode),
  V1-style AUTO-DISCOVERY from `tools/<name>` (.jsnol + scripts) and
  `skills/`/`plugins/` sentinels, alias CANONICALIZATION (`read` → `reading`,
  `file_ops`/`shell` → registered tools) and free-text tool call extraction
  (`name({...})`, `<function: name>` envelopes, `<function=name>{json}`,
  dotted `name.key = value`).
- Schema-fed planning: `V5Planner._get_tool_schemas` (NATE warm lookup first,
  then registry scan in OpenAI function format) injected into the planning
  prompt; plans whose JSON parse fails fall back to text-extracted tool calls;
  plan steps naming unknown tools are dropped with a warning. LLM plans are
  persisted to `todo.md` through the real `planning` tool
  (`V5Planner._plan_with_tool` → `_run_tool` audit/permission/event pipeline;
  failure degrades to steps-only, never breaks planning).

### V5 Modular Mixins
- `V5EventEmitter` — canonical work events (tool/stage/runtime/chunk)
- `V5ModelCaller` — real LLM calls via MoE router with timeout + provider-error fallback
- `V5ToolExecutor` — real tool execution: risk-scored commands, permission audit, auto-discovery, alias canonicalization, free-text extraction
- `V5Planner` — schema-fed LLM planning (NATE→registry) with text-fallback and unknown-tool rejection; persists plans via the `planning` tool
- `V5Logger` — structured loop logging (JSONL)
- `V5ResponseBuilder` — final-answer streaming + honest evidence-based fallback
- `V5ParallelExecutor` — V1-style smart parallelism (read gather / write sequential, repetition guard)
- `V5Verifier` — failure-evidence scan + grounded summary so success claims never lie
- `V5RetryPolicy` — tool-enforcement retry when a tool-requiring task plans no tools
- `V5Learning` — deterministic turn learning: tool-failure recording, reflection signals, JSONL turn replay (no LLM calls)
- `V5ContextBuilder` — multi-turn conversation memory from turn_history (context_summary merge, no LLM dependency)
- `V5Control` — V5 run control: abort(), _check_abort between phases, post_tool_call hooks (runtime.hooks + kernel plugins)
- `V5Hive` — opt-in sub-agent (hive) integration (NEXUS_HIVE): decompose → spawn → consolidate, `[HIVE_RESULT]` context injection, hive feedback JSON
- `V5Plugin` — plugin lifecycle hooks: safe trigger_hooks wrapper, on_session_end firing, enabled-plugin introspection
- `V5Skill` — slash-command skills (NexusSkillMaster + .opencode/skills fallback), `[SKILL_ACTIVE]` injection, skills index for context
- `V5Evolution` — background evolution (NEXUS_EVOLUTION): EvolutionLog win/lose, SelfImprovementEngine, gap backlog, MemoryForge crystallize, SkillCurator, ToolForge auto-creation, aclose draining
- `V5Cron` — scheduled one-shot tasks via tasks.scheduler.NexusTaskScheduler with CronLifecycle tracking; thread-safe runner bridging into the async loop; _stop_scheduler on shutdown
- `V5Lifecycle` — lifecycle/ framework integration: per-kind managers (tool, skill, plugin, cron, memory, self_improvement), register/transition/stats/events/hooks, _lifecycle_mark one-call helper
- `V5BackgroundRunner` — generic fire-and-forget tasks with retry/backoff, background.* events, counters, _drain_runner_tasks
- `V5Checkpoint` — durable per-phase snapshots (`.nexus/v5/checkpoints/<turn>_<phase>.json`) on every state transition + resume/load/list/clear; wired via `_checkpoint_save` in `_transition_to`
- `V5Config` — configuration access via config.NexusConfigLoader: typed getters, provider configs, directory helpers, reload, runtime seeding (permissions.mode → permission_policy, sandbox.tier → sandbox_tier); wired via _init_config at loop start
- `V5Permissions` — permission modes and checks (V5 with loop.py _init_permissions): the four main modes BYPASS / AUTO_PILOT / APPROVE / PRE_AUTHORIZED mapped from PermissionPolicy, PermissionSystem + process-wide ApprovalBroker access, pre-authorization whitelist, decision log
- `V5Sandbox` — sandbox tiers and risk scoring: NO_SANDBOX / NORMAL / DOCKER tier switching, CommandRiskScorer assessment (score/blocked/summary), sync execute + async stream_execute wrappers over SovereignSandbox; _init_security replaces core's inline copy

### Hive Integration
- Swarm intelligence extends Hive
- DAG-based topology
- Message compression

## Flow Diagram

```
User Input
    ↓
Meta-Learning (Optimize parameters based on experience)
    ↓
Perception (Multi-modal processing, intent recognition)
    ↓
PAORR-Enhanced (Dynamic planning → Parallel action → Multi-modal observation → Reflection → Adaptive retry)
    ↓
Quantum Actor (Superposition → Entanglement → Quantum parallelism → Collapse)
    ↓
Self-Evolution (Analyze → Generate → Test → Deploy → Rollback if needed)
    ↓
Emergent Behavior (Swarm intelligence → Consensus → Stigmergy)
    ↓
Consciousness (Self-awareness → Metacognition → Theory of mind → Introspection)
    ↓
Output (Multi-modal generation + Explanation + Alternatives)
```

## Canonical runtime

V5 is the only loop implementation. Import the public compatibility name or
the explicit V5 class; both resolve to the same runtime:

```python
from orchestrators import NexusLoop

loop = NexusLoop(root_dir)
result = await loop.run(user_input, input_type="text")
```

There is no legacy loop fallback. Planning, tool execution, verification, and
response handling all stay inside the V5 runtime path.

## Testing

### Unit Tests
```python
# Test meta-learning
from orchestrators.v5.meta_learning import MetaLearningLayer
layer = MetaLearningLayer(root_dir)
await layer.optimize(runtime)

# Test perception
from orchestrators.v5.perception import PerceptionLayer
layer = PerceptionLayer(root_dir)
perceived = await layer.process(turn)

# Test PAORR enhanced
from orchestrators.v5.paorr_enhanced import PAORREnhanced
loop = PAORREnhanced(root_dir)
result = await loop.execute(perceived)
```

### Integration Tests
```python
# Test full V5 loop
from orchestrators.v5 import create_v5_loop
loop = create_v5_loop(root_dir)
result = await loop.run("test input")
assert result["success"] == True
```

## Performance Monitoring

### Metrics to Track
- Turn execution time
- Meta-learning optimization time
- Quantum orchestration time
- Swarm consensus rounds
- Consciousness processing time
- Evolution deployment time

### Telemetry Integration
V5 integrates with NEXUS telemetry for:
- OpenTelemetry tracing
- Prometheus metrics
- Structured logging
- Performance dashboards

## Security Considerations

### Self-Evolution Safety
- Safe mode by default
- High confidence threshold for deployment
- Automatic rollback on failure
- Manual approval for critical changes

### Quantum Mode Safety
- Optional feature flag
- Fallback to classical mode
- Resource limits
- Timeout mechanisms

### Consciousness Safety
- Configurable consciousness level
- Metacognitive monitoring
- Theory of mind boundaries
- Introspection limits

## Future Enhancements

### Planned Features
- True quantum computing integration
- Advanced neural architecture search
- Multi-agent theory of mind
- Emergent behavior optimization
- Consciousness level auto-tuning
- Self-evolution with genetic algorithms

### Research Directions
- Quantum entanglement for distributed agents
- Swarm intelligence at scale
- Consciousness emergence
- Meta-learning for meta-learning
- Autonomous research capabilities

## V5Bench Harness

The V5Bench harness provides a unified evaluation framework for NEXUS V5, combining deterministic replay evaluation with agentic multi-persona evaluation powered by `NexusHiveEngine`.

### Components

- **V5Bench** (`bench.py`): Core bench harness that supports:
  - **Deterministic Replay Eval**: Replay recorded traces through the loop and compare outputs for regression detection.
  - **V5HiveBench Agentic Eval**: Spawns a Hive-powered evaluation session using `NexusHiveEngine` with 5 specialized personas:
    - `TESTER` — validates outputs against expected behavior and edge cases
    - `REVIEWER` — reviews code/plan quality, style, and correctness
    - `ENGINEER` — assesses architectural soundness and implementation fidelity
    - `RESEARCHER` — probes for novel insights and identifies gaps
    - `PLANNER` — evaluates plan coherence, step ordering, and feasibility

- **Bench Suite**: Collections of named scenarios with expected outcomes, tolerances, and regression thresholds.

- **Reporting**: Structured JSON reports with per-scenario pass/fail, Hive consensus scores, and regression flags.

### Usage

```python
from orchestrators.v5.bench import V5Bench, V5HiveBench

# Deterministic replay
bench = V5Bench(root_dir)
results = await bench.run_suite("regression")

# Hive-powered agentic eval
hive_bench = V5HiveBench(root_dir)
report = await hive_bench.evaluate(scenario="multi_agent_safety")
```

## V5ActiveLoop

The V5ActiveLoop is a continuous self-improving execution mode that wraps the core V5 loop with gated plan approval, bounded self-repair, and stall-driven replanning — all coordinated through the Hive.

### Key Mechanisms

- **Plan Gating**: Before execution, plans are submitted to a Hive review gate. The `PLANNER` + `REVIEWER` personas must reach consensus before the plan proceeds. Gated behind the `NEXUS_V5_ACTIVE_MODE` flag.

- **Hive-Based Bounded Self-Repair**: On verification failure, the loop invokes a bounded repair cycle (default: 3 attempts) where the `ENGINEER` persona proposes fixes and the `TESTER` persona re-validates. Repair is bounded by attempt count and wall-clock timeout.

- **Task Ledger + Stall-Driven Replan**: A persistent task ledger tracks every planned step, its status, and elapsed time. If the `PLANNER` detects a stall (no progress across a configurable window of turns), the loop triggers a Hive-driven replan: the current plan is re-evaluated, stale steps are pruned, and a revised plan is gated through the same approval flow.

- **Feature Flags**: All V5ActiveLoop features are gated behind:
  - `NEXUS_HIVE` — enables Hive-powered agentic orchestration
  - `NEXUS_V5_ACTIVE_MODE` — enables active loop mode (plan gating, self-repair, stall replan)

### Wiring

The V5ActiveLoop is wired into `core.py` via the `NexusLoopV5` orchestrator. When `NEXUS_V5_ACTIVE_MODE` is set, each PAORR cycle passes through the gating, repair, and ledger checkpoints automatically.

```python
# Active loop is enabled when both flags are set
if os.environ.get("NEXUS_HIVE") and os.environ.get("NEXUS_V5_ACTIVE_MODE"):
    loop = NexusLoopV5(root_dir, active_mode=True)
    result = await loop.run("complex multi-step task")
    # Plan gating, self-repair, and stall replan happen transparently
```

## Troubleshooting

### Common Issues

**Issue**: V5 loop not starting
- **Solution**: Check kernel integration, ensure root_dir is correct

**Issue**: Meta-learning not improving
- **Solution**: Increase experience buffer size, check learning rate

**Issue**: Quantum mode slow
- **Solution**: Reduce swarm size, disable quantum mode for complex tasks

**Issue**: Self-evolution deploying unsafe changes
- **Solution**: Enable safe mode, increase confidence threshold

**Issue**: Consciousness layer causing high latency
- **Solution**: Reduce consciousness level, disable theory of mind

## Support

For issues, questions, or contributions:
- Check documentation
- Review architecture diagrams
- Run integration tests
- Enable debug logging
- Contact NEXUS team

## License

NEXUS V5 is part of the NEXUS AI project. See main project license for details.
