"""Meta-Learning Layer - Learns how to learn for NEXUS V5.

This layer implements meta-learning capabilities:
- Hyperparameter optimization
- Architecture search
- Experience replay
- Learning rate adaptation
- Strategy selection
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime
import json
import os

logger = logging.getLogger(__name__)


@dataclass
class MetaLearningConfig:
    """Configuration for meta-learning layer."""
    learning_rate: float = 0.001
    experience_buffer_size: int = 1000
    architecture_search_enabled: bool = True
    hyperparameter_optimization_enabled: bool = True
    strategy_selection_enabled: bool = True


@dataclass
class Experience:
    """Single experience for replay."""
    task_id: str
    strategy: str
    outcome: float  # Success rate or performance metric
    timestamp: datetime
    context: Dict[str, Any] = field(default_factory=dict)
    hyperparameters: Dict[str, Any] = field(default_factory=dict)


class MetaLearningLayer:
    """Meta-learning layer that learns optimal strategies and hyperparameters."""

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.config = MetaLearningConfig()
        self.experience_buffer: List[Experience] = []
        self.strategy_performance: Dict[str, List[float]] = {}
        self.optimal_hyperparameters: Dict[str, Any] = {}
        self.tool_policy: Dict[str, Dict[str, Any]] = {}
        self.logger = logging.getLogger("nexus.v5.meta_learning")
        
        # Load saved state
        self._load_state()

    async def optimize(self, runtime: Any) -> Dict[str, Any]:
        """Apply meta-learning optimizations based on experience.
        
        Args:
            runtime: V5Runtime instance
        
        Returns:
            Dict of optimization recommendations
        """
        recommendations = {}
        
        # Hyperparameter optimization
        if self.config.hyperparameter_optimization_enabled:
            hp_recs = await self._optimize_hyperparameters(runtime)
            recommendations.update(hp_recs)
        
        # Strategy selection
        if self.config.strategy_selection_enabled:
            strategy_recs = await self._select_strategy(runtime)
            recommendations.update(strategy_recs)
        
        # Architecture search (periodic)
        if self.config.architecture_search_enabled:
            arch_recs = await self._search_architecture(runtime)
            recommendations.update(arch_recs)
        
        self.logger.info(f"Meta-learning optimization applied: {len(recommendations)} recommendations")
        return recommendations

    async def _optimize_hyperparameters(self, runtime: Any) -> Dict[str, Any]:
        """Optimize hyperparameters based on historical performance."""
        recommendations = {}
        
        # Simple adaptive learning rate based on recent performance
        if len(self.experience_buffer) > 10:
            recent_performance = [e.outcome for e in self.experience_buffer[-10:]]
            avg_performance = sum(recent_performance) / len(recent_performance)
            
            if avg_performance > 0.8:
                # Good performance, increase learning rate for faster adaptation
                new_lr = min(self.config.learning_rate * 1.1, 0.01)
            elif avg_performance < 0.5:
                # Poor performance, decrease learning rate for stability
                new_lr = max(self.config.learning_rate * 0.9, 0.0001)
            else:
                new_lr = self.config.learning_rate
            
            self.config.learning_rate = new_lr
            recommendations["learning_rate"] = new_lr
        
        return recommendations

    async def _select_strategy(self, runtime: Any) -> Dict[str, Any]:
        """Select optimal strategy based on task context."""
        recommendations = {}
        
        if not self.strategy_performance:
            return recommendations
        
        # Find best performing strategy
        best_strategy = None
        best_avg = 0.0
        
        for strategy, performances in self.strategy_performance.items():
            if len(performances) >= 3:
                avg = sum(performances[-3:]) / 3
                if avg > best_avg:
                    best_avg = avg
                    best_strategy = strategy
        
        if best_strategy:
            recommendations["recommended_strategy"] = best_strategy
            recommendations["strategy_confidence"] = best_avg
        
        return recommendations

    async def _search_architecture(self, runtime: Any) -> Dict[str, Any]:
        """Search for optimal agent architecture."""
        recommendations = {}
        
        # Simplified architecture search based on task complexity
        if runtime.current_turn:
            task_complexity = self._estimate_task_complexity(runtime.current_turn)
            
            if task_complexity > 0.8:
                recommendations["agent_topology"] = "hierarchical"
                recommendations["swarm_size"] = min(runtime.swarm_size * 2, 100)
            elif task_complexity > 0.5:
                recommendations["agent_topology"] = "dag"
                recommendations["swarm_size"] = runtime.swarm_size
            else:
                recommendations["agent_topology"] = "sequential"
                recommendations["swarm_size"] = max(runtime.swarm_size // 2, 1)
        
        return recommendations

    def _estimate_task_complexity(self, turn: Any) -> float:
        """Estimate task complexity from turn context."""
        # Simple heuristic based on input length and type
        base_complexity = 0.3
        
        if turn.input_type in ["vision", "code"]:
            base_complexity += 0.3
        
        input_length = len(turn.user_input)
        if input_length > 1000:
            base_complexity += 0.2
        elif input_length > 500:
            base_complexity += 0.1
        
        return min(base_complexity, 1.0)

    def record_experience(self, experience: Experience):
        """Record an experience for replay learning."""
        self.experience_buffer.append(experience)
        
        # Maintain buffer size
        if len(self.experience_buffer) > self.config.experience_buffer_size:
            self.experience_buffer.pop(0)
        
        # Update strategy performance
        if experience.strategy not in self.strategy_performance:
            self.strategy_performance[experience.strategy] = []
        self.strategy_performance[experience.strategy].append(experience.outcome)
        
        # Save state
        self._save_state()

    def on_verified_evidence(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """Nudge the persisted strategy performance from VERIFIED evidence only.

        A verified tool outcome updates the durable per-tool counters
        ``good_tool_count`` / ``bad_tool_count`` (with accumulated confidence)
        in the persisted ``tool_policy`` table, so later runs can see which
        tools execution has proven reliable. Assumption records never change
        policy, and ``optimize`` / ``record_experience`` semantics are
        untouched. Returns the nudges applied; never raises.
        """
        nudges: Dict[str, Any] = {}
        try:
            if not isinstance(evidence, dict):
                return nudges
            if str(evidence.get("claim_source") or "") != "verified":
                self.logger.debug("policy nudge skipped: evidence is not verified")
                return nudges
            kind = str(evidence.get("kind") or "")
            if kind not in {
                "tool_outcome", "failure", "retry_success", "test_outcome",
                "verification", "user_correction",
            }:
                return nudges
            provenance = evidence.get("provenance")
            if not isinstance(provenance, dict):
                return nudges
            tool = str(provenance.get("tool_name") or "").strip()
            if not tool:
                return nudges
            confidence = float(evidence.get("confidence") or 0.0)
            confidence = max(0.0, min(1.0, confidence))
            policy = self.tool_policy.setdefault(tool, {
                "good_tool_count": 0,
                "bad_tool_count": 0,
                "good_confidence_sum": 0.0,
                "bad_confidence_sum": 0.0,
            })
            polarity = str(evidence.get("polarity") or "")
            if polarity == "positive":
                policy["good_tool_count"] = int(policy.get("good_tool_count", 0)) + 1
                policy["good_confidence_sum"] = round(
                    float(policy.get("good_confidence_sum", 0.0)) + confidence, 4
                )
                nudges["tool"] = tool
                nudges["good_tool_count"] = policy["good_tool_count"]
            elif polarity == "negative":
                policy["bad_tool_count"] = int(policy.get("bad_tool_count", 0)) + 1
                policy["bad_confidence_sum"] = round(
                    float(policy.get("bad_confidence_sum", 0.0)) + confidence, 4
                )
                nudges["tool"] = tool
                nudges["bad_tool_count"] = policy["bad_tool_count"]
            else:
                return nudges
            policy["updated_at"] = datetime.now().isoformat()
            self._save_state()
        except Exception as e:
            self.logger.warning(f"Meta-learning policy nudge skipped: {e}")
        return nudges

    def _load_state(self):
        """Load meta-learning state from disk."""
        state_file = os.path.join(self.root_dir, ".nexus_v5_meta_learning.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                    self.config = MetaLearningConfig(**state.get("config", {}))
                    self.strategy_performance = state.get("strategy_performance", {})
                    self.optimal_hyperparameters = state.get("optimal_hyperparameters", {})
                    self.tool_policy = state.get("tool_policy", {})
            except Exception as e:
                self.logger.warning(f"Failed to load meta-learning state: {e}")

    def _save_state(self):
        """Save meta-learning state to disk."""
        state_file = os.path.join(self.root_dir, ".nexus_v5_meta_learning.json")
        try:
            state = {
                "config": {
                    "learning_rate": self.config.learning_rate,
                    "experience_buffer_size": self.config.experience_buffer_size,
                    "architecture_search_enabled": self.config.architecture_search_enabled,
                    "hyperparameter_optimization_enabled": self.config.hyperparameter_optimization_enabled,
                    "strategy_selection_enabled": self.config.strategy_selection_enabled,
                },
                "strategy_performance": self.strategy_performance,
                "optimal_hyperparameters": self.optimal_hyperparameters,
                "tool_policy": self.tool_policy,
            }
            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to save meta-learning state: {e}")
