import os
import json
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer
from peft import LoraConfig, get_peft_model
from datasets import Dataset
import logging

# 🔱 [PROTOCOL_SATURATION]: Forcefully Locking NEXUS JSON standards

logging.basicConfig(level=logging.ERROR)

def _training_model_path(root):
    try:
        from core.config_loader import NexusConfigLoader
        config = NexusConfigLoader().get_provider_config("SOVEREIGN_BRAIN")
        rel_path = config.get("model_path")
        if rel_path:
            return os.path.join(root, rel_path)
    except Exception:
        pass
    return os.path.join(root, "models", "local", "qwen3.5-0.8b-uncensored-opus-distill")

def run_saturation():
    _ROOT = os.getcwd()
    # Master Unity (Agentic, Logic, Persona)
    model_id = _training_model_path(_ROOT)
    if not os.path.isdir(model_id):
        raise FileNotFoundError(
            f"Training model directory not found: {model_id}. "
            "Set providers.local.SOVEREIGN_BRAIN.model_path or NEXUS_PROVIDERS_LOCAL_SOVEREIGN_BRAIN_MODEL_PATH "
            "to a local Transformers model directory."
        )
    synth_path = os.path.join(_ROOT, "training_data", "mega_unity_dataset.json")
    
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch.float32, low_cpu_mem_usage=True)

    config = LoraConfig(
        r=32, # 💠 ULTRA-HIGH RANK FOR PROTOCOL LOCK
        lora_alpha=64, 
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj"], 
        lora_dropout=0.05, 
        bias="none", 
        task_type="CAUSAL_LM"
    )
    model = get_peft_model(model, config)
    model.to(device)

    final_params = []
    with open(synth_path, "r") as f:
        synths = json.load(f)
        for item in synths:
            parts = item["text"].split("\nNexus: ")
            if len(parts) == 2:
                user_q = parts[0].replace("User: ", "")
                # 🛑 THE TARGET: Must be literal action/params JSON
                nexus_a = parts[1].replace("TASK_COMPLETE", "").strip()
                chatml = f"<|im_start|>system\nYou are Nexus. Execute tools using strict JSON schema: {{'action': '...', 'params': {{...}}}}<|im_end|>\n"
                chatml += f"<|im_start|>user\n{user_q}<|im_end|>\n"
                chatml += f"<|im_start|>assistant\n{nexus_a}<|im_end|>\n"
                final_params.append(chatml)

    # Extreme Saturation (1000 items)
    dataset = Dataset.from_dict({"text": final_params * 50})

    def tokenize_function(examples):
        return tokenizer(examples['text'], padding="max_length", truncation=True, max_length=128)

    tokenized_datasets = dataset.map(tokenize_function, batched=True, remove_columns=["text"])
    
    def add_labels(examples):
        examples["labels"] = examples["input_ids"].copy()
        return examples

    train_dataset = tokenized_datasets.map(add_labels, batched=True)

    print("\n[*] Engaging MASTER SATURATION (300 Steps - MEGA UNITY DATASET)...")
    training_args = TrainingArguments(
        output_dir="./nexus_saturation_cache",
        learning_rate=3e-5, # 🛡️ STABLE HEALING RATE
        per_device_train_batch_size=4,
        gradient_accumulation_steps=1,
        dataloader_num_workers=0,
        max_steps=300,
        logging_steps=10,
        save_strategy="no",
        fp16=torch.cuda.is_available(),
        optim="adamw_torch",
        report_to="none"
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
    )

    trainer.train()

    output_path = model_id
    os.makedirs(output_path, exist_ok=True)
    model.save_pretrained(output_path)
    tokenizer.save_pretrained(output_path)
    print(f"SUCCESS: NEXUS PROTOCOL SATURATION COMPLETE [ {output_path} ]")

if __name__ == "__main__":
    run_saturation()
