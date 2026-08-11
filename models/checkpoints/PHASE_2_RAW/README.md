---
base_model: HuggingFaceTB/SmolLM2-135M-Instruct
library_name: peft
pipeline_tag: text-generation
tags:
- base_model:adapter:HuggingFaceTB/SmolLM2-135M-Instruct
- lora
- transformers
---

# NEXUS LoRA Checkpoint — PHASE_2_RAW

Raw (unpruned) PEFT LoRA adapter checkpoint from Phase 2 of the NEXUS local-brain fine-tuning pipeline (see `scripts/nexus_trainer.py` and `evolution/local_trainer/`). Retained as a reference baseline before further phases and GGUF conversion.

## Model Details

- **Base model:** HuggingFaceTB/SmolLM2-135M-Instruct
- **Adapter type:** LoRA (PEFT 0.18.1)
- **Task type:** CAUSAL_LM
- **Rank (`r`):** 8
- **Alpha:** 16
- **Target modules:** `q_proj`, `v_proj`
- **Dropout:** 0.0
- **Inference mode:** true

## Usage

Load the adapter over the base model:

```python
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

base = AutoModelForCausalLM.from_pretrained("HuggingFaceTB/SmolLM2-135M-Instruct")
model = PeftModel.from_pretrained(base, "models/checkpoints/PHASE_2_RAW")
tokenizer = AutoTokenizer.from_pretrained("HuggingFaceTB/SmolLM2-135M-Instruct")
```

## Notes

- Internal experimental checkpoint produced by NEXUS's own training scripts; not intended for standalone distribution.
- Training-data details, hyperparameters, and evaluation logs for this phase are managed by the evolution/local_trainer pipeline, not in this card.
