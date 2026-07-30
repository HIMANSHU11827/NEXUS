# Local Trainer
**Version:** 2.0.0

Local fine-tuning system for embedding + LLM models. Triggered by NATE when routing quality dips. Outputs GGUF for efficient local inference.

## Components
- `EmbeddingFinetuner` — Fine-tune embedding models
- `LLMFinetuner` — Fine-tune LLMs locally
- `LocalTrainer` — Orchestrator for training workflows
- `SelfImprovementLifecycle` — Lifecycle hooks for self-improvement
- `TrainingDataCollector` — Collect and prepare training data
