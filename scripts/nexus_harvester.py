import os
import json
import random
from datasets import load_dataset
from tqdm import tqdm

# 🌌 THE DECAGON OF SINGULARITY: 10 Core Categories
CATEGORIES = {
    "SYSTEM_KERNEL": ("m-a-p/TerminalBench", "test", 300),
    "CODE_FORGE": ("ise-uiuc/Magicoder-OSS-Instruct-75K", "train", 300),
    "AGENTIC_LOOP": ("Salesforce/xlam-function-calling-60k", "train", 300),
    "STRATEGIC_PLAN": ("THUDM/AgentBench", "os", 300), 
    "KNOWLEDGE_SYNTH": ("microsoft/orca-math-word-problems-200k", "train", 300),
    "MULTI_TURN_CHAT": ("HuggingFaceTB/smoltalk", "all", 300),
    "LOGIC_PROVING": ("gsm8k", "main", 300),
    "SECURITY_AUDIT": ("m-a-p/TerminalBench", "test", 100), # Placeholder for security subset
    "HIVE_MASTERY": ("Salesforce/xlam-function-calling-60k", "train", 100), # Placeholder
    "SELF_EVOLUTION": ("HuggingFaceTB/smoltalk", "all", 100) # Placeholder
}

def harvest(samples_per_cat=100):
    print(f"[*] Starting Neural Harvest: {samples_per_cat} samples/category...")
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(_ROOT, "training_data", "harvest")
    os.makedirs(output_dir, exist_ok=True)

    master_dataset = []

    for cat, (repo, split, _) in CATEGORIES.items():
        print(f"    [+] Harvesting {cat} from {repo}...")
        try:
            # Load a small streaming sample to save time
            ds = load_dataset(repo, split=split, streaming=True, trust_remote_code=True)
            iterator = iter(ds)
            count = 0
            while count < samples_per_cat:
                try:
                    item = next(iterator)
                except StopIteration:
                    break
                # Normalize format to ChatML
                text = ""
                if "instruction" in item and "output" in item:
                    text = f"<|im_start|>system\nYou are Nexus. Category: {cat}<|im_end|>\n<|im_start|>user\n{item['instruction']}<|im_end|>\n<|im_start|>assistant\n{item['output']}<|im_end|>"
                elif "query" in item and "answer" in item:
                    text = f"<|im_start|>system\nYou are Nexus. Category: {cat}<|im_end|>\n<|im_start|>user\n{item['query']}<|im_end|>\n<|im_start|>assistant\n{item['answer']}<|im_end|>"
                elif "messages" in item:
                    # Handle chat formats
                    text = f"<|im_start|>system\nYou are Nexus. Category: {cat}<|im_end|>\n"
                    for msg in item["messages"]:
                        role = msg["role"]
                        content = msg["content"]
                        text += f"<|im_start|>{role}\n{content}<|im_end|>\n"
                
                if text:
                    master_dataset.append({"category": cat, "text": text})
                    count += 1
        except Exception as e:
            print(f"    [!] Error harvesting {cat}: {e}")

    output_path = os.path.join(output_dir, f"nexus_harvest_{samples_per_cat}.json")
    with open(output_path, "w") as f:
        json.dump(master_dataset, f, indent=2)
    
    print(f"SUCCESS: {len(master_dataset)} samples harvested to {output_path}")
    return output_path

if __name__ == "__main__":
    harvest(100)
    harvest(200)
