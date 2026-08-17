"""Emergent Behavior Layer - Swarm intelligence for NEXUS V5.

This module implements:
- Swarm intelligence
- Consensus algorithms
- Self-organizing networks
- Stigmergy (indirect communication)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from enum import Enum
import random
import math

logger = logging.getLogger(__name__)


class SwarmTopology(str, Enum):
    """Swarm topology types."""
    FULL_MESH = "full_mesh"
    HUB_AND_SPOKE = "hub_and_spoke"
    RING = "ring"
    TREE = "tree"
    RANDOM = "random"


@dataclass
class SwarmAgent:
    """A single agent in the swarm."""
    agent_id: str
    state: Dict[str, Any] = field(default_factory=dict)
    neighbors: Set[str] = field(default_factory=set)
    role: str = "worker"
    energy: float = 1.0


@dataclass
class ConsensusResult:
    """Result of consensus algorithm."""
    decision: Any
    agreement_level: float
    participating_agents: int
    rounds: int


class EmergentBehaviorLayer:
    """Emergent behavior layer for swarm intelligence."""

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.logger = logging.getLogger("nexus.v5.emergent_behavior")
        self.swarm_agents: Dict[str, SwarmAgent] = {}
        self.topology = SwarmTopology.HUB_AND_SPOKE
        self.environment_state: Dict[str, Any] = {}

    async def process(self, result: Dict[str, Any], swarm_size: int) -> Dict[str, Any]:
        """Process result through emergent behavior layer.
        
        Args:
            result: Result from previous layer
            swarm_size: Number of agents in swarm
        
        Returns:
            Dict with swarm-processed results
        """
        self.logger.info(f"Processing with swarm of size {swarm_size}")
        
        # Defensive guard: no swarm behavior for a single agent
        if swarm_size <= 1:
            return result
        
        # Cap swarm size to avoid pathological loop counts
        swarm_size = min(swarm_size, 50)
        
        # Initialize swarm
        await self._initialize_swarm(swarm_size)
        
        # Apply swarm intelligence
        swarm_result = await self._apply_swarm_intelligence(result)
        
        # Run consensus algorithm
        consensus = await self._run_consensus(swarm_result)
        
        # Apply stigmergy (indirect communication)
        stigmergy_result = await self._apply_stigmergy(consensus)
        
        return {
            "success": True,
            "swarm_result": swarm_result,
            "consensus": consensus,
            "stigmergy": stigmergy_result,
            "swarm_size": swarm_size
        }

    async def _initialize_swarm(self, swarm_size: int):
        """Initialize swarm agents with topology."""
        self.swarm_agents = {}
        
        # Create agents
        for i in range(swarm_size):
            agent = SwarmAgent(
                agent_id=f"swarm_agent_{i}",
                role="hub" if i == 0 else "worker",
                energy=1.0
            )
            self.swarm_agents[agent.agent_id] = agent
        
        # Build topology
        await self._build_topology()

    async def _build_topology(self):
        """Build communication topology."""
        agent_ids = list(self.swarm_agents.keys())
        
        if self.topology == SwarmTopology.FULL_MESH:
            # Everyone connected to everyone
            for agent_id in agent_ids:
                self.swarm_agents[agent_id].neighbors = set(agent_ids) - {agent_id}
        
        elif self.topology == SwarmTopology.HUB_AND_SPOKE:
            # Hub (first agent) connected to all workers
            hub = agent_ids[0]
            workers = agent_ids[1:]
            self.swarm_agents[hub].neighbors = set(workers)
            for worker in workers:
                self.swarm_agents[worker].neighbors = {hub}
        
        elif self.topology == SwarmTopology.RING:
            # Ring topology
            for i, agent_id in enumerate(agent_ids):
                next_agent = agent_ids[(i + 1) % len(agent_ids)]
                prev_agent = agent_ids[(i - 1) % len(agent_ids)]
                self.swarm_agents[agent_id].neighbors = {next_agent, prev_agent}
        
        elif self.topology == SwarmTopology.TREE:
            # Simple tree (hub as root, workers as children)
            hub = agent_ids[0]
            workers = agent_ids[1:]
            self.swarm_agents[hub].neighbors = set(workers)
            for worker in workers:
                self.swarm_agents[worker].neighbors = {hub}

    async def _apply_swarm_intelligence(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Apply swarm intelligence to process result."""
        self.logger.info("Applying swarm intelligence")
        
        # Distribute task among swarm
        tasks = []
        for agent_id, agent in self.swarm_agents.items():
            if agent.energy > 0.1:
                task = self._agent_process(agent, result)
                tasks.append(task)
        
        # Execute in parallel
        agent_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Aggregate results
        aggregated = self._aggregate_results(agent_results)
        
        return aggregated

    async def _agent_process(self, agent: SwarmAgent, result: Dict[str, Any]) -> Dict[str, Any]:
        """Process task for a single agent."""
        self.logger.debug(f"Agent {agent.agent_id} processing")
        
        # Simulate agent processing
        await asyncio.sleep(0.05)
        
        # Agent adds its perspective
        agent_result = {
            "agent_id": agent.agent_id,
            "role": agent.role,
            "perspective": f"Agent {agent.agent_id} view",
            "confidence": random.uniform(0.5, 1.0),
            "energy": agent.energy
        }
        
        # Update agent energy
        agent.energy = max(0.0, agent.energy - 0.1)
        
        return agent_result

    def _aggregate_results(self, agent_results: List[Any]) -> Dict[str, Any]:
        """Aggregate results from all agents."""
        valid_results = [r for r in agent_results if not isinstance(r, Exception)]
        
        if not valid_results:
            return {"error": "No valid agent results"}
        
        # Weighted aggregation by confidence
        total_weight = sum(r.get("confidence", 1.0) for r in valid_results)
        
        aggregated = {
            "agent_count": len(valid_results),
            "total_weight": total_weight,
            "average_confidence": total_weight / len(valid_results) if valid_results else 0.0,
            "perspectives": [r.get("perspective") for r in valid_results]
        }
        
        return aggregated

    async def _run_consensus(self, swarm_result: Dict[str, Any]) -> ConsensusResult:
        """Run consensus algorithm to reach agreement."""
        self.logger.info("Running consensus algorithm")
        
        agents = list(self.swarm_agents.values())
        rounds = 0
        max_rounds = 10
        convergence_threshold = 0.8
        
        # Initial opinions
        opinions = {agent.agent_id: random.uniform(0.0, 1.0) for agent in agents}
        
        while rounds < max_rounds:
            rounds += 1
            
            # Each agent updates opinion based on neighbors
            new_opinions = {}
            for agent in agents:
                neighbor_opinions = [
                    opinions[neighbor_id]
                    for neighbor_id in agent.neighbors
                    if neighbor_id in opinions
                ]
                
                if neighbor_opinions:
                    # Average with neighbors
                    new_opinion = (opinions[agent.agent_id] + sum(neighbor_opinions)) / (len(neighbor_opinions) + 1)
                else:
                    new_opinion = opinions[agent.agent_id]
                
                new_opinions[agent.agent_id] = new_opinion
            
            opinions = new_opinions
            
            # Check convergence
            opinion_values = list(opinions.values())
            avg_opinion = sum(opinion_values) / len(opinion_values)
            variance = sum((o - avg_opinion) ** 2 for o in opinion_values) / len(opinion_values)
            
            if variance < (1 - convergence_threshold):
                break
        
        # Final decision
        final_decision = avg_opinion > 0.5
        agreement_level = 1.0 - variance
        
        return ConsensusResult(
            decision=final_decision,
            agreement_level=agreement_level,
            participating_agents=len(agents),
            rounds=rounds
        )

    async def _apply_stigmergy(self, consensus: ConsensusResult) -> Dict[str, Any]:
        """Apply stigmergy (indirect communication through environment)."""
        self.logger.info("Applying stigmergy")
        
        # Agents leave pheromones in environment
        for agent_id, agent in self.swarm_agents.items():
            if agent.energy > 0.2:
                # Leave pheromone based on consensus
                pheromone_strength = consensus.agreement_level * agent.energy
                self.environment_state[f"pheromone_{agent_id}"] = pheromone_strength
        
        # Agents sense pheromones and adjust behavior
        total_pheromone = sum(
            v for k, v in self.environment_state.items()
            if k.startswith("pheromone_")
        )
        
        stigmergy_result = {
            "pheromone_count": len([k for k in self.environment_state.keys() if k.startswith("pheromone_")]),
            "total_pheromone": total_pheromone,
            "consensus_influenced": total_pheromone > len(self.swarm_agents) * 0.5
        }
        
        return stigmergy_result

    async def self_organize(self):
        """Self-organize network topology."""
        self.logger.info("Self-organizing network")
        
        # Calculate optimal topology based on agent count and energy
        agent_count = len(self.swarm_agents)
        avg_energy = sum(a.energy for a in self.swarm_agents.values()) / agent_count if agent_count > 0 else 0
        
        if agent_count > 20 and avg_energy > 0.7:
            self.topology = SwarmTopology.TREE
        elif agent_count > 10:
            self.topology = SwarmTopology.HUB_AND_SPOKE
        else:
            self.topology = SwarmTopology.FULL_MESH
        
        # Rebuild topology
        await self._build_topology()
        
        self.logger.info(f"Self-organized to {self.topology} topology")
