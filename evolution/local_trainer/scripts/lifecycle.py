"""Self-Improving Lifecycle — NATE harvests data → fine-tune → GGUF → run → repeat.

Flow:
  1. NATE runs, logs every tool call + routing decision → training_data/harvest/
  2. When harvest count ≥ threshold → auto-trigger fine-tune
  3. Fine-tune embedding model (better NATE-Route) + Zupra-50M (better local brain)
  4. Export → GGUF q8_0
  5. Replace old models → reload into NATE + llama.cpp
  6. Repeat — self-improving cycle
"""

import json
import logging
import os
import shutil
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("NEXUS_LIFECYCLE")


class TrainingDataCollector:
    """Collects tool interaction data from NATE for self-training.

    Every tool call, routing decision, and feedback is logged
    as a structured example for future fine-tuning.
    """

    def __init__(self, harvest_dir: str = ""):
        _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.harvest_dir = harvest_dir or os.path.join(_ROOT, "training_data", "harvest")
        os.makedirs(self.harvest_dir, exist_ok=True)
        self._session_buffer: List[Dict] = []

    def log_tool_call(self, query: str, tool_name: str, params: Dict,
                      result: str, success: bool, latency_ms: float) -> None:
        """Log a single tool interaction as training example."""
        example = {
            "timestamp": time.time(),
            "query": query,
            "tool_called": tool_name,
            "params": params,
            "result": result[:500],
            "success": success,
            "latency_ms": round(latency_ms, 1),
        }
        self._session_buffer.append(example)

    def log_routing(self, query: str, selected_tools: List[str],
                    confidence: float, path: str) -> None:
        """Log NATE-Route routing decision."""
        example = {
            "timestamp": time.time(),
            "query": query,
            "selected_tools": selected_tools,
            "confidence": round(confidence, 3),
            "path": path,
            "type": "routing",
        }
        self._session_buffer.append(example)

    def log_feedback(self, tool_name: str, query: str, success: bool) -> None:
        """Log OATS feedback as training example."""
        example = {
            "timestamp": time.time(),
            "query": query,
            "tool_called": tool_name,
            "success": success,
            "type": "oats_feedback",
        }
        self._session_buffer.append(example)

    def flush(self, filename: str = "") -> str:
        """Write session buffer to disk as JSONL."""
        if not self._session_buffer:
            return ""

        fname = filename or f"harvest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        path = os.path.join(self.harvest_dir, fname)

        with open(path, "a", encoding="utf-8") as f:
            for ex in self._session_buffer:
                f.write(json.dumps(ex) + "\n")

        count = len(self._session_buffer)
        self._session_buffer.clear()
        logger.info(f"[HARVEST] Flushed {count} examples → {path}")
        return path

    def count_harvest(self) -> int:
        """Count total training examples collected."""
        total = 0
        if not os.path.isdir(self.harvest_dir):
            return 0
        for fname in os.listdir(self.harvest_dir):
            if fname.endswith(".jsonl"):
                fpath = os.path.join(self.harvest_dir, fname)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        total += sum(1 for _ in f)
                except Exception:
                    logger.warning("evolution/local_trainer/lifecycle.py:102 count_harvest: suppressed error", exc_info=True)
                    pass
        return total

    def get_harvest_summary(self) -> Dict[str, Any]:
        """Summary of collected training data."""
        total = self.count_harvest()
        files = []
        if os.path.isdir(self.harvest_dir):
            for fname in sorted(os.listdir(self.harvest_dir)):
                if fname.endswith(".jsonl"):
                    fpath = os.path.join(self.harvest_dir, fname)
                    files.append({
                        "name": fname,
                        "size": os.path.getsize(fpath),
                        "modified": datetime.fromtimestamp(os.path.getmtime(fpath)).isoformat(),
                    })

        return {
            "total_examples": total,
            "harvest_dir": self.harvest_dir,
            "files": files[-10:],
            "session_buffer": len(self._session_buffer),
        }


class SelfImprovementLifecycle:
    """Autonomous fine-tuning lifecycle.

    Attached to NATE evolve phase. Runs every N queries.
    Checks harvest count → triggers fine-tune → exports GGUF → reloads.
    """

    MIN_EMBED_EXAMPLES = 20
    MIN_LLM_EXAMPLES = 50
    CHECK_INTERVAL = 100  # Check every N queries

    def __init__(self, nate_instance: Any):
        self.nate = nate_instance
        self.collector = TrainingDataCollector()
        self._last_check = 0
        self._cycles_completed = 0
        self._last_cycle_time = 0

    def on_tool_call(self, query: str, tool_name: str, params: Dict,
                     result: str, success: bool, latency_ms: float) -> None:
        """Called by NATE after every tool execution."""
        self.collector.log_tool_call(query, tool_name, params, result, success, latency_ms)

    def on_routing(self, query: str, selected_tools: List[str],
                   confidence: float, path: str) -> None:
        """Called by NATE after every routing decision."""
        self.collector.log_routing(query, selected_tools, confidence, path)

    def on_feedback(self, tool_name: str, query: str, success: bool) -> None:
        """Called by NATE when OATS feedback recorded."""
        self.collector.log_feedback(tool_name, query, success)

    def should_cycle(self, force: bool = False) -> bool:
        """Check if enough data has accumulated for a training cycle."""
        if force:
            return True

        total = self.collector.count_harvest()
        if total < self.MIN_EMBED_EXAMPLES:
            return False

        time_since = time.time() - self._last_cycle_time
        if time_since < 300:  # Minimum 5 min between cycles
            return False

        return True

    def run_cycle(self, force: bool = False) -> Dict[str, Any]:
        """Run one full training cycle: harvest → fine-tune → GGUF → reload."""
        if not self.should_cycle(force):
            return {"status": "skipped", "reason": "not_enough_data"}

        t0 = time.time()
        logger.info(f"[LIFECYCLE] Starting cycle #{self._cycles_completed + 1}")

        # 1. Flush any buffered data
        self.collector.flush()

        # 2. Check totals
        total = self.collector.count_harvest()
        results = {
            "cycle": self._cycles_completed + 1,
            "total_examples": total,
            "embedding": False,
            "llm": False,
            "gguf_embed": False,
            "gguf_llm": False,
        }

        # 3. Fine-tune embedding model
        if total >= self.MIN_EMBED_EXAMPLES:
            logger.info("[LIFECYCLE] Phase 1: Fine-tuning embedding model...")
            from evolution.local_trainer.scripts.embedding_trainer import (
                EmbeddingFinetuner,
            )

            embed = EmbeddingFinetuner()
            logs = self._build_training_logs("routing")
            embed_result = embed.finetune(logs, output_dir="models/local/embed-finetuned")

            if embed_result:
                results["embedding"] = True
                # Export to GGUF
                if embed.export_gguf("models/local/embed-finetuned.gguf"):
                    results["gguf_embed"] = True
                    # Reload into NATE router
                    try:
                        from sentence_transformers import SentenceTransformer
                        self.nate.schema_engine.router._model = SentenceTransformer("models/local/embed-finetuned")
                        self.nate.schema_engine.router._rebuild_clusters()
                        logger.info("[LIFECYCLE] Embedding model reloaded into NATE")
                    except Exception as e:
                        logger.warning(f"[LIFECYCLE] Embedding reload failed: {e}")

        # 4. Fine-tune Zupra-50M
        if total >= self.MIN_LLM_EXAMPLES:
            logger.info("[LIFECYCLE] Phase 2: Fine-tuning Zupra-50M...")
            from evolution.local_trainer.scripts.llm_trainer import LLMFinetuner

            llm = LLMFinetuner()
            logs = self._build_training_logs("tool_call")
            llm_result = llm.finetune(logs, output_dir="models/local/zupra-finetuned")

            if llm_result:
                results["llm"] = True
                if llm.export_gguf("zupra-finetuned.gguf"):
                    results["gguf_llm"] = True

        # 5. Run GGUF — convert fine-tuned model to GGUF for local inference
        gguf_path = self._run_gguf_export(results)
        if gguf_path:
            results["gguf_path"] = gguf_path

        # 6. Register GGUF model with llama.cpp provider
        if gguf_path:
            self._register_gguf_model(gguf_path)

        # 7. Archive old harvest files
        self._archive_old_harvest()

        # 8. Update metrics
        self._cycles_completed += 1
        self._last_cycle_time = time.time()
        elapsed = time.time() - t0
        results["elapsed_s"] = round(elapsed, 1)
        results["status"] = "completed"

        logger.info(f"[LIFECYCLE] Cycle #{self._cycles_completed} done in {elapsed:.1f}s: {results}")
        return results

    def _run_gguf_export(self, results: Dict) -> Optional[str]:
        """Convert fine-tuned models → GGUF for llama.cpp inference."""
        try:
            import subprocess
            import sys
            _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            convert_script = os.path.join(_ROOT, "vendor", "llama.cpp", "convert_hf_to_gguf.py")

            if not os.path.exists(convert_script):
                logger.warning("[LIFECYCLE] convert_hf_to_gguf.py not found. Install llama.cpp in vendor/")
                return None

            # Find merged model
            merged_dirs = []
            for d in ["models/local/zupra-finetuned_merged", "models/local/zupra-finetuned"]:
                full = os.path.join(_ROOT, d)
                if os.path.isdir(full):
                    merged_dirs.append(full)

            if not merged_dirs:
                logger.info("[LIFECYCLE] No fine-tuned model to export to GGUF")
                return None

            model_dir = merged_dirs[0]
            output_path = os.path.join(_ROOT, "models", "local", "zupra-finetuned.gguf")
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            cmd = [sys.executable, convert_script, model_dir, "--outfile", output_path, "--outtype", "q8_0"]
            logger.info(f"[LIFECYCLE] Exporting GGUF: {' '.join(cmd[-4:])}")
            subprocess.run(cmd, check=True, capture_output=True, timeout=300)

            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            logger.info(f"[LIFECYCLE] GGUF exported: {output_path} ({size_mb:.0f}MB)")

            # Clean up merged dir
            import shutil
            for d in merged_dirs:
                shutil.rmtree(d, ignore_errors=True)

            return output_path

        except Exception as e:
            logger.warning(f"[LIFECYCLE] GGUF export failed: {e}")
            return None

    def _register_gguf_model(self, gguf_path: str) -> None:
        """Register GGUF model with llama.cpp provider so NATE can use it."""
        try:
            from models.providers.local.llama_cpp import LlamaCPPProvider
            provider = LlamaCPPProvider()

            if provider.llm:
                logger.info(f"[LIFECYCLE] GGUF model already loaded: {gguf_path}")
            else:
                logger.info(f"[LIFECYCLE] GGUF model ready at: {gguf_path}")

            self._gguf_model_path = gguf_path
        except Exception as e:
            logger.debug(f"[LIFECYCLE] GGUF registration: {e}")

    def _build_training_logs(self, filter_type: str = "") -> List[Dict]:
        """Read harvest files and return structured training logs."""
        logs = []
        harvest_dir = self.collector.harvest_dir
        if not os.path.isdir(harvest_dir):
            return logs

        for fname in sorted(os.listdir(harvest_dir)):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(harvest_dir, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        ex = json.loads(line)
                        if filter_type and ex.get("type") != filter_type and filter_type == "routing":
                            if "selected_tools" not in ex:
                                continue
                        logs.append(ex)
            except Exception:
                logger.warning("evolution/local_trainer/lifecycle.py:338 : suppressed error", exc_info=True)
                pass

        return logs

    def _archive_old_harvest(self) -> None:
        """Move processed harvest files to archive after training."""
        harvest_dir = self.collector.harvest_dir
        archive_dir = os.path.join(harvest_dir, "..", "archive")
        os.makedirs(archive_dir, exist_ok=True)

        for fname in os.listdir(harvest_dir):
            if fname.endswith(".jsonl"):
                src = os.path.join(harvest_dir, fname)
                dst = os.path.join(archive_dir, fname)
                try:
                    shutil.move(src, dst)
                except Exception:
                    logger.warning("evolution/local_trainer/lifecycle.py:355 _archive_old_harvest: suppressed error", exc_info=True)
                    pass

    def status(self) -> Dict[str, Any]:
        """Return lifecycle status."""
        return {
            "cycles_completed": self._cycles_completed,
            "last_cycle": datetime.fromtimestamp(self._last_cycle_time).isoformat() if self._last_cycle_time else "never",
            "harvest": self.collector.get_harvest_summary(),
            "config": {
                "min_embed_examples": self.MIN_EMBED_EXAMPLES,
                "min_llm_examples": self.MIN_LLM_EXAMPLES,
                "check_interval": self.CHECK_INTERVAL,
            },
        }
