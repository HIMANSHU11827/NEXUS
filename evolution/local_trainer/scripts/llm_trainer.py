"""LLM fine-tuner — improves local Zupra-50M model for tool calling.
Uses LoRA on Zupra-1.6-50M-Instruct-Ultra-exp.
Output: merged LoRA → GGUF q8_0 for llama.cpp inference.
"""

import json
import logging
import os
import subprocess
import sys
import time
from typing import Dict, List

logger = logging.getLogger("NEXUS_LLM_TRAIN")

MODEL_ID = "MultivexAI/Zupra-1.6-50M-Instruct-Ultra-exp"


class LLMFinetuner:
    """Fine-tune Zupra-50M using LoRA on tool-calling data.

    Triggered when NATE detects the local model needs to learn new tools
    or improve response quality for specific domains.
    """

    def __init__(self, model_name: str = MODEL_ID):
        self.model_name = model_name
        self._trained = False
        self._output_dir = ""

    def prepare_data(self, tool_logs: List[Dict]) -> List[Dict]:
        """Convert NATE tool interaction logs to training format.

        Each entry: {"instruction": "call tool X", "output": "tool result"}
        """
        examples = []
        for log in tool_logs:
            query = log.get("query", "")
            tool = log.get("tool_called", "")
            result = log.get("result", "")
            if query and tool:
                examples.append({
                    "instruction": query,
                    "output": json.dumps({"tool": tool, "result": result}),
                })
        return examples

    def finetune(self, tool_logs: List[Dict], output_dir: str = "models/local/zupra-finetuned",
                 epochs: int = 3, lora_r: int = 16, lora_alpha: int = 32) -> bool:
        """Fine-tune Zupra-50M with LoRA on tool-calling data."""
        data = self.prepare_data(tool_logs)
        if len(data) < 3:
            logger.warning(f"[LLM_TRAIN] Too few examples ({len(data)}), skipping")
            return False

        self._output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        logger.info(f"[LLM_TRAIN] Starting LoRA fine-tune: {len(data)} examples, {epochs} epochs")

        try:
            import torch
            from datasets import Dataset
            from peft import LoraConfig, TaskType, get_peft_model
            from transformers import (
                AutoModelForCausalLM,
                AutoTokenizer,
                DataCollatorForSeq2Seq,
                Trainer,
                TrainingArguments,
            )

            # Load model
            t0 = time.time()
            model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                torch_dtype=torch.float16,
                device_map="auto",
                trust_remote_code=True,
            )
            tokenizer = AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True)
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token

            # LoRA config
            lora_config = LoraConfig(
                r=lora_r,
                lora_alpha=lora_alpha,
                target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
                lora_dropout=0.05,
                bias="none",
                task_type=TaskType.CAUSAL_LM,
            )
            model = get_peft_model(model, lora_config)
            model.print_trainable_parameters()

            # Format data
            def format_example(ex):
                text = f"### Instruction:\n{ex['instruction']}\n\n### Response:\n{ex['output']}{tokenizer.eos_token}"
                return tokenizer(text, truncation=True, max_length=512, padding=False)

            dataset = Dataset.from_list(data).map(format_example)

            # Training args
            training_args = TrainingArguments(
                output_dir=output_dir,
                per_device_train_batch_size=4,
                gradient_accumulation_steps=2,
                num_train_epochs=epochs,
                learning_rate=2e-4,
                fp16=True,
                save_steps=50,
                logging_steps=10,
                save_total_limit=1,
                remove_unused_columns=False,
                report_to="none",
            )

            trainer = Trainer(
                model=model,
                args=training_args,
                train_dataset=dataset,
                data_collator=DataCollatorForSeq2Seq(tokenizer, pad_to_multiple_of=8),
            )

            trainer.train()
            trainer.save_model(output_dir)
            tokenizer.save_pretrained(output_dir)

            elapsed = time.time() - t0
            logger.info(f"[LLM_TRAIN] Done in {elapsed:.1f}s, saved to {output_dir}")

            # Merge LoRA for GGUF export
            logger.info("[LLM_TRAIN] Merging LoRA weights...")
            merged = model.merge_and_unload()
            merged_dir = output_dir + "_merged"
            merged.save_pretrained(merged_dir)
            tokenizer.save_pretrained(merged_dir)
            logger.info(f"[LLM_TRAIN] Merged model at {merged_dir}")

            self._trained = True
            return True

        except Exception as e:
            logger.error(f"[LLM_TRAIN] Failed: {e}")
            return False

    def export_gguf(self, output_name: str = "zupra-finetuned.gguf") -> bool:
        """Convert fine-tuned model to GGUF q8_0 for llama.cpp."""
        if not self._trained or not self._output_dir:
            logger.warning("[LLM_TRAIN] No trained model to export")
            return False

        merged_dir = self._output_dir + "_merged"
        if not os.path.exists(merged_dir):
            logger.warning(f"[LLM_TRAIN] Merged dir not found: {merged_dir}")
            return False

        _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        convert_script = os.path.join(_ROOT, "vendor", "llama.cpp", "convert_hf_to_gguf.py")

        if not os.path.exists(convert_script):
            logger.warning("[LLM_TRAIN] convert_hf_to_gguf.py not found, skipping GGUF")
            return False

        output_path = os.path.join(_ROOT, "models", "local", output_name)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        try:
            cmd = [sys.executable, convert_script, merged_dir, "--outfile", output_path, "--outtype", "q8_0"]
            subprocess.run(cmd, check=True, capture_output=True)
            logger.info(f"[LLM_TRAIN] GGUF exported: {output_path}")

            # Clean up merged dir
            import shutil
            shutil.rmtree(merged_dir, ignore_errors=True)

            return True
        except Exception as e:
            logger.error(f"[LLM_TRAIN] GGUF export failed: {e}")
            return False
