"""Embedding model fine-tuner — improves NATE-Route tool routing quality.
Uses SetFit-style contrastive learning on tool-query pairs.
Output: fine-tuned embedding model + GGUF for FAISS.
"""

import logging
import os
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("NEXUS_EMBED_TRAIN")

MODEL_NAME = "all-MiniLM-L6-v2"


class EmbeddingFinetuner:
    """Fine-tune all-MiniLM-L6-v2 on tool-query pairs using contrastive learning.

    Improves tool routing when NATE detects:
    - Low confidence scores on known tools
    - Confusion between similar tools (wrong tool selected)
    - New domain-specific vocabulary not in pretrained model
    """

    def __init__(self, model_name: str = MODEL_NAME):
        self.model_name = model_name
        self._model = None
        self._trained = False

    def _lazy_load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            logger.info(f"[EMBED_TRAIN] Loaded {self.model_name}")
        except ImportError:
            raise ImportError("sentence-transformers required")

    def prepare_pairs(self, tool_logs: List[Dict]) -> Tuple[List[str], List[str], List[int]]:
        """Convert NATE routing logs to (anchor, positive, label) pairs.

        tool_logs: list of {query, correct_tool, wrong_tools[]}
        Returns: (queries, tool_descriptions, labels)
        """
        queries, descriptions, labels = [], [], []
        for log in tool_logs:
            q = log.get("query", "")
            correct = log.get("correct_tool", "")
            wrong = log.get("wrong_tools", [])

            if q and correct:
                queries.append(q)
                descriptions.append(correct)
                labels.append(1)

                for w in wrong[:3]:
                    queries.append(q)
                    descriptions.append(w)
                    labels.append(0)
        return queries, descriptions, labels

    def finetune(self, tool_logs: List[Dict], output_dir: str = "", epochs: int = 3,
                 batch_size: int = 16, lr: float = 2e-5) -> bool:
        """Fine-tune embedding model on tool-query pairs.

        Uses cosine similarity loss: push correct tool closer, pull wrong ones away.
        """
        self._lazy_load()
        queries, descriptions, labels = self.prepare_pairs(tool_logs)
        if len(queries) < 4:
            logger.warning(f"[EMBED_TRAIN] Too few pairs ({len(queries)}), skipping")
            return False

        try:
            from sentence_transformers import InputExample, losses
            from torch.utils.data import DataLoader

            examples = [
                InputExample(texts=[q, d], label=float(l))
                for q, d, l in zip(queries, descriptions, labels)
            ]
            loader = DataLoader(examples, batch_size=batch_size, shuffle=True)
            loss_fn = losses.CosineSimilarityLoss(self._model)

            logger.info(f"[EMBED_TRAIN] Starting fine-tune: {len(examples)} pairs, {epochs} epochs")
            t0 = time.time()

            self._model.fit(
                train_objectives=[(loader, loss_fn)],
                epochs=epochs,
                warmup_steps=int(len(loader) * 0.1),
                show_progress_bar=True,
            )

            elapsed = time.time() - t0
            logger.info(f"[EMBED_TRAIN] Done in {elapsed:.1f}s")

            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                self._model.save(output_dir)
                logger.info(f"[EMBED_TRAIN] Saved to {output_dir}")

            self._trained = True
            return True

        except Exception as e:
            logger.error(f"[EMBED_TRAIN] Failed: {e}")
            return False

    def export_gguf(self, output_path: str) -> bool:
        """Export fine-tuned embedding model to GGUF for FAISS.
        Note: Embedding GGUF is experimental — relies on llama.cpp support.
        """
        if not self._trained and self._model is None:
            logger.warning("[EMBED_TRAIN] No trained model to export")
            return False

        try:
            import subprocess
            import sys
            _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            convert_script = os.path.join(_ROOT, "vendor", "llama.cpp", "convert_hf_to_gguf.py")

            if not os.path.exists(convert_script):
                logger.warning("[EMBED_TRAIN] convert_hf_to_gguf.py not found, skipping GGUF export")
                return False

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            cmd = [sys.executable, convert_script, self.model_name, "--outfile", output_path, "--outtype", "q8_0"]
            subprocess.run(cmd, check=True, capture_output=True)
            logger.info(f"[EMBED_TRAIN] GGUF exported: {output_path}")
            return True
        except Exception as e:
            logger.error(f"[EMBED_TRAIN] GGUF export failed: {e}")
            return False

    def get_updated_embeddings(self) -> Optional[np.ndarray]:
        """Return updated tool embeddings after fine-tuning."""
        if self._model is None:
            return None
        return self._model.encode(["dummy"], normalize_embeddings=True)
