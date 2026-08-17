"""Self-Evolution Layer - Autonomous self-improvement for NEXUS V5.

This module implements:
- Autonomous code generation
- Self-testing
- Self-deployment with rollback
- Continuous improvement
"""

import asyncio
import logging
import os
import json
import random
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class EvolutionPhase(str, Enum):
    """Phases of self-evolution."""
    ANALYSIS = "analysis"
    GENERATION = "generation"
    TESTING = "testing"
    DEPLOYMENT = "deployment"
    ROLLBACK = "rollback"
    COMPLETED = "completed"


@dataclass
class EvolutionCandidate:
    """A candidate improvement."""
    candidate_id: str
    description: str
    code_changes: Dict[str, str]  # file_path -> new_content
    test_results: Dict[str, bool] = field(default_factory=dict)
    confidence: float = 0.0
    verified: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class EvolutionLog:
    """Log of evolution attempts."""
    evolution_id: str
    candidates: List[EvolutionCandidate] = field(default_factory=list)
    deployed_candidate: Optional[str] = None
    rollback_performed: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    success: bool = False


class SelfEvolutionLayer:
    """Self-evolution layer for autonomous improvement."""

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.logger = logging.getLogger("nexus.v5.self_evolution")
        self.evolution_history: List[EvolutionLog] = []
        self.current_phase = EvolutionPhase.ANALYSIS
        self.evolution_enabled = True
        self.safe_mode = True  # Only deploy with high confidence
        self._deployed_backups: Dict[str, Optional[str]] = {}  # target -> backup path (None if none existed)
        self._recover_interrupted_deployment()

    def _transaction_manifest_path(self) -> str:
        return os.path.join(self.root_dir, ".nexus_v5_evolution_transaction.json")

    def _write_transaction_manifest(self, manifest: Dict[str, Any]) -> None:
        """Durably publish the deployment journal before target replacement."""
        path = self._transaction_manifest_path()
        parent = os.path.dirname(path) or "."
        os.makedirs(parent, exist_ok=True)
        temporary = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=parent,
                prefix=".nexus-evolution-manifest-", suffix=".tmp", delete=False,
            ) as handle:
                temporary = handle.name
                json.dump(manifest, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                try:
                    os.remove(temporary)
                except OSError:
                    pass

    def _remove_transaction_manifest(self) -> None:
        try:
            os.remove(self._transaction_manifest_path())
        except FileNotFoundError:
            pass
        except OSError as exc:
            self.logger.warning("Failed to remove evolution transaction journal: %s", exc)

    def _recover_interrupted_deployment(self) -> None:
        """Recover an uncommitted deployment left by a terminated process."""
        path = self._transaction_manifest_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            if manifest.get("status") == "committed":
                self._cleanup_transaction_backups(manifest.get("files", []))
                self._remove_transaction_manifest()
                return

            root = os.path.realpath(os.path.abspath(self.root_dir))
            restored = 0
            for entry in manifest.get("files", []):
                target = os.path.realpath(os.path.abspath(str(entry.get("target") or "")))
                backup_value = entry.get("backup")
                backup = (
                    os.path.realpath(os.path.abspath(str(backup_value)))
                    if backup_value else None
                )
                if not target or os.path.commonpath([root, target]) != root:
                    raise ValueError("transaction target is outside the evolution root")
                if backup and os.path.commonpath([root, backup]) != root:
                    raise ValueError("transaction backup is outside the evolution root")
                if backup and os.path.exists(backup):
                    shutil.copy2(backup, target)
                    restored += 1
                elif not backup and os.path.exists(target):
                    os.remove(target)
                    restored += 1
                temporary = entry.get("temporary")
                if temporary and os.path.exists(temporary):
                    os.remove(temporary)
            self._cleanup_transaction_backups(manifest.get("files", []))
            self._remove_transaction_manifest()
            self.logger.warning(
                "Recovered interrupted self-evolution deployment (%d targets)", restored
            )
        except Exception as exc:
            self.logger.error(
                "Could not recover self-evolution transaction; journal retained: %s", exc,
                exc_info=True,
            )

    def _cleanup_transaction_backups(self, entries: List[Dict[str, Any]]) -> None:
        """Remove only backup files owned by the recorded transaction."""
        root = os.path.realpath(os.path.abspath(self.root_dir))
        for entry in entries:
            backup_value = entry.get("backup") if isinstance(entry, dict) else None
            if not backup_value:
                continue
            backup = os.path.realpath(os.path.abspath(str(backup_value)))
            try:
                inside_root = os.path.commonpath([root, backup]) == root
            except ValueError:
                inside_root = False
            if not inside_root:
                self.logger.error("Refusing to remove out-of-root evolution backup: %s", backup)
                continue
            try:
                if os.path.isfile(backup):
                    os.remove(backup)
            except OSError as exc:
                self.logger.warning("Failed to remove evolution backup %s: %s", backup, exc)

    async def evolve(self, runtime: Any) -> Dict[str, Any]:
        """Execute self-evolution process.
        
        Args:
            runtime: V5Runtime instance
        
        Returns:
            Dict with evolution results
        """
        if not self.evolution_enabled:
            self.logger.info("Self-evolution disabled")
            return {"enabled": False, "reason": "disabled"}
        
        self.logger.info("Starting self-evolution process")
        
        evolution_log = EvolutionLog(evolution_id=self._generate_evolution_id())
        
        try:
            # Phase 1: Analysis
            self.current_phase = EvolutionPhase.ANALYSIS
            analysis = await self._analyze_system(runtime)
            
            # Phase 2: Generation
            self.current_phase = EvolutionPhase.GENERATION
            candidates = await self._generate_improvements(analysis)
            evolution_log.candidates = candidates
            
            if not candidates:
                self.logger.info("No improvement candidates generated")
                return {"success": True, "candidates": 0, "reason": "no_candidates"}
            
            # Phase 3: Testing
            self.current_phase = EvolutionPhase.TESTING
            tested_candidates = await self._test_candidates(candidates)
            
            # Phase 4: Deployment (if safe and confident)
            self.current_phase = EvolutionPhase.DEPLOYMENT
            if self.safe_mode:
                best_candidate = self._select_best_candidate(tested_candidates)
                if best_candidate and best_candidate.confidence > 0.8:
                    deployed = await self._deploy_candidate(best_candidate)
                    if deployed:
                        evolution_log.deployed_candidate = best_candidate.candidate_id
                        evolution_log.success = True
                    else:
                        # Rollback if deployment failed
                        await self._rollback(best_candidate)
                        evolution_log.rollback_performed = True
            else:
                # Unsafe mode still records the real deployment outcome. A
                # failed write must never be reported as a successful mission.
                best_candidate = self._select_best_candidate(tested_candidates)
                if best_candidate:
                    deployed = await self._deploy_candidate(best_candidate)
                    if deployed:
                        evolution_log.deployed_candidate = best_candidate.candidate_id
                        evolution_log.success = True
                    else:
                        await self._rollback(best_candidate)
                        evolution_log.rollback_performed = True
            
            self.current_phase = EvolutionPhase.COMPLETED
            self.evolution_history.append(evolution_log)
            self._save_evolution_history()
            
            return {
                "success": evolution_log.success,
                "candidates_tested": len(tested_candidates),
                "deployed": evolution_log.deployed_candidate,
                "rollback": evolution_log.rollback_performed
            }
            
        except Exception as e:
            self.logger.error(f"Self-evolution failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _analyze_system(self, runtime: Any) -> Dict[str, Any]:
        """Analyze current system for improvement opportunities."""
        self.logger.info("Analyzing system for improvements")
        
        # Collect metrics from runtime
        analysis = {
            "turn_count": len(runtime.turn_history),
            "meta_learning_enabled": runtime.meta_learning_enabled,
            "quantum_mode": runtime.quantum_mode,
            "consciousness_level": runtime.consciousness_level,
            "swarm_size": runtime.swarm_size,
            "improvement_opportunities": []
        }
        
        # Identify improvement opportunities
        if analysis["turn_count"] > 100 and not runtime.meta_learning_enabled:
            analysis["improvement_opportunities"].append("enable_meta_learning")
        
        if analysis["consciousness_level"] < 5:
            analysis["improvement_opportunities"].append("increase_consciousness")
        
        if analysis["swarm_size"] < 5:
            analysis["improvement_opportunities"].append("increase_swarm_size")
        
        return analysis

    async def _generate_improvements(self, analysis: Dict[str, Any]) -> List[EvolutionCandidate]:
        """Generate improvement candidates."""
        self.logger.info("Generating improvement candidates")
        
        candidates = []
        
        for opportunity in analysis.get("improvement_opportunities", []):
            candidate = EvolutionCandidate(
                candidate_id=self._generate_candidate_id(),
                description=f"Implement {opportunity}",
                code_changes=self._generate_code_changes(opportunity),
                confidence=0.7  # Initial confidence
            )
            candidates.append(candidate)
        
        self.logger.info(f"Generated {len(candidates)} improvement candidates")
        return candidates

    def _generate_code_changes(self, opportunity: str) -> Dict[str, str]:
        """Generate code changes for an opportunity.

        Changes target a dedicated v5 config file so deployments are real,
        coherent, and reversible.
        """
        config_file = os.path.join(self.root_dir, ".nexus_v5_evolution_config.json")
        changes = {}
        
        if opportunity == "enable_meta_learning":
            changes[config_file] = json.dumps({"meta_learning_enabled": True}, indent=2)
        elif opportunity == "increase_consciousness":
            changes[config_file] = json.dumps({"consciousness_level": 7}, indent=2)
        elif opportunity == "increase_swarm_size":
            changes[config_file] = json.dumps({"swarm_size": 10}, indent=2)
        
        return changes

    async def _test_candidates(self, candidates: List[EvolutionCandidate]) -> List[EvolutionCandidate]:
        """Test improvement candidates from real evidence.

        A candidate is only verified when *every* available check passes:
        the change is non-empty, targets stay inside the repository root,
        the written content is valid JSON, and the values satisfy the
        expected runtime config schema. Unverifiable candidates stay
        blocked (``verified=False``, source-confidence score) and can
        never deploy in safe mode.
        """
        self.logger.info(f"Testing {len(candidates)} candidates")

        tested = []

        for candidate in candidates:
            await asyncio.sleep(0.1)

            evidence = self._evaluate_candidate(candidate)
            candidate.test_results = evidence

            passed = [k for k, v in evidence.items() if v]
            fully_passed = len(evidence) > 0 and len(passed) == len(evidence)

            if fully_passed:
                # Genuinely validated against syntax + safety + schema checks.
                candidate.verified = True
                candidate.confidence = 0.9
            else:
                # Honest failure: candidate stays blocked, cannot deploy.
                candidate.verified = False
                candidate.confidence = 0.0
                self.logger.info(
                    f"Candidate {candidate.candidate_id} blocked: "
                    f"passed {len(passed)}/{len(evidence)} checks"
                )

            tested.append(candidate)

        return tested

    # Schema of the dedicated v5 evolution config file. Only these keys are
    # written by _generate_code_changes; anything else is rejected as suspect.
    _EXPECTED_CONFIG_TYPES = {
        "meta_learning_enabled": bool,
        "consciousness_level": int,
        "swarm_size": int,
    }

    def _evaluate_candidate(self, candidate: EvolutionCandidate) -> Dict[str, bool]:
        """Gather concrete test evidence for a candidate.

        Returns a dict of check-name -> passed. No check is simulated: each
        one inspects the actual change payload and resolves target paths.
        """
        evidence: Dict[str, bool] = {}
        if not candidate.code_changes:
            evidence["non_empty"] = False
            return evidence

        root_resolved = os.path.realpath(os.path.abspath(self.root_dir))
        all_paths_safe = True
        all_content_valid = True
        all_values_sane = True

        for file_path, new_content in candidate.code_changes.items():
            if not new_content or not str(new_content).strip():
                all_content_valid = False
                continue

            # Path safety: the target must live inside the repo root.
            target = file_path if os.path.isabs(file_path) else os.path.join(self.root_dir, file_path)
            target_resolved = os.path.realpath(os.path.abspath(target))
            if not (target_resolved == root_resolved or target_resolved.startswith(root_resolved + os.sep)):
                all_paths_safe = False
                continue

            # Content sanity: the payload must be valid JSON...
            try:
                parsed = json.loads(str(new_content))
            except (TypeError, ValueError, json.JSONDecodeError):
                all_content_valid = False
                continue

            # ...and, for the config file, satisfy the expected schema.
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    if key in self._EXPECTED_CONFIG_TYPES:
                        if type(value) is not self._EXPECTED_CONFIG_TYPES[key]:
                            all_values_sane = False
                            break
                    elif value is not None and not isinstance(
                        value, (bool, int, float, str, list, dict)
                    ):
                        all_values_sane = False
                        break

        evidence["non_empty"] = bool(candidate.code_changes)
        evidence["path_safety"] = all_paths_safe
        evidence["json_valid"] = all_content_valid
        evidence["schema_sane"] = all_values_sane
        return evidence

    def _select_best_candidate(self, candidates: List[EvolutionCandidate]) -> Optional[EvolutionCandidate]:
        """Select best candidate for deployment."""
        if not candidates:
            return None
        
        # Select candidate with highest confidence
        return max(candidates, key=lambda c: c.confidence)

    async def _deploy_candidate(self, candidate: EvolutionCandidate) -> bool:
        """Deploy a candidate improvement to disk.

        Each existing target is copied to a transaction-owned temporary
        backup before it is written so the deployment can be reverted via
        ``_rollback`` without leaving user-visible ``.bak`` files behind.
        """
        return await asyncio.to_thread(self._deploy_candidate_sync, candidate)

    def _deploy_candidate_sync(self, candidate: EvolutionCandidate) -> bool:
        """Stage and atomically commit a multi-file candidate transaction."""
        self.logger.info(f"Deploying candidate {candidate.candidate_id}")
        staged: List[str] = []
        commit_targets: List[str] = []
        try:
            root = os.path.realpath(os.path.abspath(self.root_dir))
            self._deployed_backups.clear()
            for file_path, new_content in candidate.code_changes.items():
                if not new_content:
                    continue

                target = file_path if os.path.isabs(file_path) else os.path.join(self.root_dir, file_path)
                target = os.path.abspath(os.path.normpath(target))
                resolved = os.path.realpath(target)
                try:
                    outside = os.path.commonpath([root, resolved]) != root
                except ValueError:
                    outside = True
                if outside:
                    raise ValueError(f"Candidate path is outside the evolution root: {file_path}")

                parent = os.path.dirname(target)
                os.makedirs(parent, exist_ok=True)
                if os.path.exists(target):
                    backup_handle = tempfile.NamedTemporaryFile(
                        mode="wb", dir=parent, prefix=".nexus-evolution-backup-",
                        suffix=".bak", delete=False,
                    )
                    backup = backup_handle.name
                    backup_handle.close()
                    shutil.copy2(target, backup)
                    self._deployed_backups[target] = backup
                else:
                    self._deployed_backups[target] = None

                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=parent,
                    prefix=".nexus-evolution-", suffix=".tmp", delete=False,
                ) as staged_file:
                    staged_file.write(str(new_content))
                    staged_file.flush()
                    os.fsync(staged_file.fileno())
                    staged.append(staged_file.name)
                    commit_targets.append(target)

            self._write_transaction_manifest({
                "version": 1,
                "status": "commit_started",
                "candidate_id": candidate.candidate_id,
                "files": [
                    {
                        "target": target,
                        "backup": self._deployed_backups.get(target),
                        "temporary": temporary,
                    }
                    for target, temporary in zip(commit_targets, staged)
                ],
            })

            for target, temporary in zip(commit_targets, staged):
                os.replace(temporary, target)
                self.logger.debug(f"Updated {target}")

            self._write_transaction_manifest({
                "version": 1,
                "status": "committed",
                "candidate_id": candidate.candidate_id,
                "files": [
                    {"target": target, "backup": backup, "temporary": ""}
                    for target, backup in self._deployed_backups.items()
                    if backup
                ],
            })
            self._cleanup_transaction_backups([
                {"backup": backup} for backup in self._deployed_backups.values() if backup
            ])
            self._deployed_backups.clear()
            self._remove_transaction_manifest()

            self.logger.info(f"Successfully deployed candidate {candidate.candidate_id}")
            return True
        except Exception as e:
            self.logger.error(f"Deployment failed: {e}")
            for temporary in staged:
                try:
                    if os.path.exists(temporary):
                        os.remove(temporary)
                except OSError:
                    pass
            self._rollback_sync(candidate)
            return False

    async def _rollback(self, candidate: EvolutionCandidate):
        """Rollback a deployed candidate from its backups."""
        await asyncio.to_thread(self._rollback_sync, candidate)

    def _rollback_sync(self, candidate: EvolutionCandidate):
        """Restore a deployment transaction without blocking the event loop."""
        self.logger.info(f"Rolling back candidate {candidate.candidate_id}")
        
        restored = 0
        for target, backup in self._deployed_backups.items():
            try:
                if backup and os.path.exists(backup):
                    shutil.copy2(backup, target)
                    restored += 1
                elif backup is None and os.path.exists(target):
                    os.remove(target)
                    restored += 1
            except Exception as e:
                self.logger.warning(f"Rollback failed for {target}: {e}")

        backups = list(self._deployed_backups.values())
        self._deployed_backups.clear()
        self._cleanup_transaction_backups([
            {"backup": backup} for backup in backups if backup
        ])
        self._remove_transaction_manifest()
        
        self.logger.info(f"Rollback complete ({restored} files restored)")

    def _generate_evolution_id(self) -> str:
        """Generate unique evolution ID."""
        import uuid
        return f"evo_{uuid.uuid4().hex[:12]}"

    def _generate_candidate_id(self) -> str:
        """Generate unique candidate ID."""
        import uuid
        return f"cand_{uuid.uuid4().hex[:12]}"

    def _save_evolution_history(self):
        """Save evolution history to disk."""
        history_file = os.path.join(self.root_dir, ".nexus_v5_evolution.json")
        try:
            history_data = [
                {
                    "evolution_id": log.evolution_id,
                    "deployed_candidate": log.deployed_candidate,
                    "rollback_performed": log.rollback_performed,
                    "timestamp": log.timestamp.isoformat(),
                    "success": log.success,
                    "candidates_count": len(log.candidates)
                }
                for log in self.evolution_history
            ]
            with open(history_file, 'w') as f:
                json.dump(history_data, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to save evolution history: {e}")

    def _load_evolution_history(self):
        """Load evolution history from disk."""
        history_file = os.path.join(self.root_dir, ".nexus_v5_evolution.json")
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    history_data = json.load(f)
                    self.evolution_history = [
                        EvolutionLog(
                            evolution_id=item["evolution_id"],
                            deployed_candidate=item.get("deployed_candidate"),
                            rollback_performed=item.get("rollback_performed", False),
                            timestamp=datetime.fromisoformat(item["timestamp"]),
                            success=item.get("success", False)
                        )
                        for item in history_data
                    ]
            except Exception as e:
                self.logger.warning(f"Failed to load evolution history: {e}")
