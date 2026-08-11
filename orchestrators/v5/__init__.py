"""NEXUS V5 Loop - Self-adaptive quantum loop architecture.

This package contains the V5 loop implementation with:
- Meta-Learning Layer
- Perception Layer
- Enhanced PAORR Loop
- Quantum Actor Model
- Self-Evolution Layer
- Emergent Behavior Layer
- Consciousness Layer
- Output Layer
- Modular Mixins (V5): events, model, tools, planning, response, parallel, verification, retry, learning, context, control, hive, plugin, skill, evolution, cron, lifecycle, log, background_runner, config, permissions, sandbox
"""

from .core import (
    NexusLoopV5, V5LoopState, V5TurnContext, V5Runtime,
    PermissionPolicy, ToolCall, HookRegistry  # V5 integration
)
from .meta import MetaLearningLayer, MetaLearningConfig, Experience
from .perceive import PerceptionLayer, PerceivedInput, InputType, Intent
from .paorr import PAORREnhanced, Plan, PlanStep, ActionResult, Observation, Reflection, PAORRPhase
from .quantum import QuantumActorModel, QuantumActor, QuantumMessage, QuantumState
from .self_evolution import SelfEvolutionLayer, EvolutionCandidate, EvolutionLog, EvolutionPhase
from .emergent import EmergentBehaviorLayer, SwarmAgent, ConsensusResult
from .conscious import ConsciousnessLayer, SelfModel, MentalState, TheoryOfMindModel, ConsciousnessLevel
from .output import OutputLayer, OutputResult, OutputType
from .context_manager import ContextManager, ContextConfig, ContextSnapshot  # V5 integration
from .orchestrator import V5Orchestrator, create_v5_loop
from .context import V5ContextBuilder
from .control import V5Control
from .events import V5EventEmitter
from .model import V5ModelCaller
from .direct_loop import V5DirectModelToolLoop
from .tools import V5ToolExecutor
from .planning import V5Planner
from .response import V5ResponseBuilder
from .parallel import V5ParallelExecutor
from .verification import V5Verifier
from .programmatic_verify import (
    ProgrammaticVerificationResult,
    VerificationCommandFact,
    run_programmatic_verification,
)
from .verification_recipes import VerificationRecipe, detect_verification_recipe
from .retry import V5RetryPolicy
from .learning import V5Learning
from .hive import V5Hive
from .plugin import V5Plugin
from .skill import V5Skill
from .evolution import V5Evolution
from .cron import V5Cron
from .lifecycle import V5Lifecycle
from .log import V5Logger
from .background_runner import V5BackgroundRunner
from .config import V5Config
from .permissions import V5Permissions
from .sandbox import V5Sandbox
from .bench import V5Bench, V5HiveBench
from .active_loop import V5ActiveLoop
from .compat import V5Compat
from .grounding import V5ContextGrounding

__all__ = [
    # Core
    "NexusLoopV5",
    "V5LoopState",
    "V5TurnContext",
    "V5Runtime",
    # V5 Integration
    "PermissionPolicy",
    "ToolCall",
    "HookRegistry",
    "ContextManager",
    "ContextConfig",
    "ContextSnapshot",
    # Meta-Learning
    "MetaLearningLayer",
    "MetaLearningConfig",
    "Experience",
    # Perception
    "PerceptionLayer",
    "PerceivedInput",
    "InputType",
    "Intent",
    # PAORR Enhanced
    "PAORREnhanced",
    "Plan",
    "PlanStep",
    "ActionResult",
    "Observation",
    "Reflection",
    "PAORRPhase",
    # Quantum Actor
    "QuantumActorModel",
    "QuantumActor",
    "QuantumMessage",
    "QuantumState",
    # Self-Evolution
    "SelfEvolutionLayer",
    "EvolutionCandidate",
    "EvolutionLog",
    "EvolutionPhase",
    # Emergent Behavior
    "EmergentBehaviorLayer",
    "SwarmAgent",
    "ConsensusResult",
    # Consciousness
    "ConsciousnessLayer",
    "SelfModel",
    "MentalState",
    "TheoryOfMindModel",
    "ConsciousnessLevel",
    # Output
    "OutputLayer",
    "OutputResult",
    "OutputType",
    # Orchestrator
    "V5Orchestrator",
    "create_v5_loop",
    # Modular Mixins (V5)
    "V5EventEmitter",
    "V5ModelCaller",
    "V5DirectModelToolLoop",
    "V5ToolExecutor",
    "V5Planner",
    "V5ResponseBuilder",
    "V5ParallelExecutor",
    "V5Verifier",
    "V5RetryPolicy",
    "V5Learning",
    "V5ContextBuilder",
    "V5Control",
    "V5Hive",
    "V5Plugin",
    "V5Skill",
    "V5Evolution",
    "V5Cron",
    "V5Lifecycle",
    "V5Logger",
    "V5BackgroundRunner",
    "V5Config",
    "V5Permissions",
    "V5Sandbox",
    # Bench / Eval
    "V5Bench",
    "V5HiveBench",
    # Active Loop (Hive-powered gating + repair)
    "V5ActiveLoop",
    # Compat (V1 subsystem integration)
    "V5Compat",
    # Context Grounding (workspace + knowledge context)
    "V5ContextGrounding",
]
