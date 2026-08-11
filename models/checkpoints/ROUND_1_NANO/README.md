---
base_model: HuggingFaceTB/SmolLM2-135M-Instruct
library_name: peft
pipeline_tag: text-generation
tags:
- base_model:adapter:HuggingFaceTB/SmolLM2-135M-Instruct
- lora
- transformers
---

# NEXUS Nano LoRA Checkpoint — ROUND_1_NANO

PEFT LoRA adapter checkpoint for the NEXUS local-brain fine-tuning pipeline (see `scripts/nexus_trainer.py` and `evolution/local_trainer/`). This is a small nano-scale round of micro-memory fine-tuning on the SmolLM2-135M-Instruct base model.

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

Load the adapter over the base model (requires the `ml` optional dependency group):

```python
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

base = AutoModelForCausalLM.from_pretrained("HuggingFaceTB/SmolLM2-135M-Instruct")
model = PeftModel.from_pretrained(base, "models/checkpoints/ROUND_1_NANO")
tokenizer = AutoTokenizer.from_pretrained("HuggingFaceTB/SmolLM2-135M-Instruct")
```

## Notes

- Internal experimental checkpoint produced by NEXUS's own training scripts; not intended for standalone distribution.
- Training-data details, hyperparameters, and evaluation logs for this round are managed by the evolution/local_trainer pipeline, not in this card.
