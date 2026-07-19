"""Local Fine-Tuning System for Embedding + LLM models.
Triggered by NATE when routing quality dips. Outputs GGUF for efficient local inference.
"""
from evolution.local_trainer.scripts.embedding_trainer import EmbeddingFinetuner
from evolution.local_trainer.scripts.lifecycle import (
           SelfImprovementLifecycle,
           TrainingDataCollector,
)
from evolution.local_trainer.scripts.llm_trainer import LLMFinetuner
from evolution.local_trainer.scripts.trainer import LocalTrainer

__all__ = ["EmbeddingFinetuner", "LLMFinetuner", "LocalTrainer",
           "SelfImprovementLifecycle", "TrainingDataCollector"]
