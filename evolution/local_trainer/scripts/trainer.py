"""LocalTrainer orchestrator — auto-decides when to fine-tune.
Triggered by NATE when routing quality drops or new tools added.
"""

import logging
import os
import time
from typing import Any, Dict, List

logger = logging.getLogger("NEXUS_LOCAL_TRAIN")


class LocalTrainer:
    """Orchestrates local fine-tuning of embedding + LLM models.

    Trigger conditions (monitored by NATE):
    1. NATE-Route confidence drops below threshold for known tools
    2. OATS feedback accumulates >50 corrections
    3. New tools added (re-index + fine-tune)
    4. Manual trigger from user

    Flow:
      1. Collect routing logs from NATE
      2. Fine-tune embedding model (improves tool selection)
      3. Fine-tune Zupra-50M (improves tool calling)
      4. Export both → GGUF
      5. Reload into NATE + llama.cpp
    """

    def __init__(self, data_dir: str = ""):
        _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.data_dir = data_dir or os.path.join(_ROOT, "training_data", "harvest")
        self._embedder = None
        self._llm = None

    def collect_logs(self, nate_instance: Any) -> List[Dict]:
        """Extract routing logs from NATE engine for training.

        Reads OATS feedback, routing failures, and low-confidence queries.
        """
        logs = []
        try:
            router = nate_instance.schema_engine.router
            success_fb = getattr(router, "_feedback_success", {})
            failure_fb = getattr(router, "_feedback_failure", {})

            for tool_name, embeddings in success_fb.items():
                logs.append({
                    "query": f"use {tool_name}",
                    "correct_tool": tool_name,
                    "wrong_tools": list(failure_fb.keys())[:3],
                    "tool_called": tool_name,
                    "result": "success",
                })

            for tool_name, embeddings in failure_fb.items():
                logs.append({
                    "query": f"use {tool_name}",
                    "correct_tool": "",
                    "wrong_tools": [tool_name],
                    "tool_called": tool_name,
                    "result": "failure",
                })
        except Exception as e:
            logger.debug(f"[LOCAL_TRAIN] Log collection: {e}")

        return logs

    def should_train(self, nate_instance: Any) -> Dict[str, bool]:
        """Check if fine-tuning is needed based on NATE metrics."""
        try:
            router = nate_instance.schema_engine.router
            stats = router.stats()
            feedback_count = sum(
                len(v) for v in getattr(router, "_feedback_success", {}).values()
            ) + sum(
                len(v) for v in getattr(router, "_feedback_failure", {}).values()
            )

            needs_embed = feedback_count >= 20
            needs_llm = feedback_count >= 50

            return {
                "needs_embed_training": needs_embed,
                "needs_llm_training": needs_llm,
                "feedback_count": feedback_count,
                "path1_pct": stats.get("path1_pct", 0),
                "avg_latency_ms": stats.get("avg_latency_ms", 0),
            }
        except Exception as e:
            logger.debug(f"[LOCAL_TRAIN] Should train check: {e}")
            return {"needs_embed_training": False, "needs_llm_training": False, "feedback_count": 0}

    def train_embedding(self, nate_instance: Any, output_dir: str = "") -> bool:
        """Fine-tune embedding model if conditions met."""
        from evolution.local_trainer.scripts.embedding_trainer import EmbeddingFinetuner

        logs = self.collect_logs(nate_instance)
        if len(logs) < 4:
            logger.info("[LOCAL_TRAIN] Not enough logs for embedding training")
            return False

        self._embedder = EmbeddingFinetuner()
        result = self._embedder.finetune(logs, output_dir=output_dir)

        if result and self._embedder:
            # Update NATE router with fine-tuned model
            try:
                router = nate_instance.schema_engine.router
                router._model = self._embedder._model
                router._rebuild_clusters()
                logger.info("[LOCAL_TRAIN] Embedding model updated in NATE router")
            except Exception as e:
                logger.warning(f"[LOCAL_TRAIN] Router update failed: {e}")

        return result

    def train_llm(self, nate_instance: Any, output_dir: str = "") -> bool:
        """Fine-tune Zupra-50M if conditions met."""
        from evolution.local_trainer.scripts.llm_trainer import LLMFinetuner

        logs = self.collect_logs(nate_instance)
        if len(logs) < 3:
            logger.info("[LOCAL_TRAIN] Not enough logs for LLM training")
            return False

        self._llm = LLMFinetuner()
        return self._llm.finetune(logs, output_dir=output_dir)

    def train_all(self, nate_instance: Any) -> Dict[str, Any]:
        """Auto-train both models with single call. Called by NATE evolve phase."""
        t0 = time.time()
        decision = self.should_train(nate_instance)
        results = {"embedding": False, "llm": False, "gguf": False}

        if decision.get("needs_embed_training"):
            logger.info("[LOCAL_TRAIN] Auto-triggering embedding fine-tune")
            results["embedding"] = self.train_embedding(nate_instance)

        if decision.get("needs_llm_training"):
            logger.info("[LOCAL_TRAIN] Auto-triggering LLM fine-tune")
            results["llm"] = self.train_llm(nate_instance)

        elapsed = time.time() - t0
        results["elapsed_s"] = round(elapsed, 1)
        results["decision"] = decision
        logger.info(f"[LOCAL_TRAIN] Done in {elapsed:.1f}s: {results}")
        return results
