import os
import json

CATEGORIES = [
    "SYSTEM_KERNEL", "CODE_FORGE", "AGENTIC_LOOP", "STRATEGIC_PLAN", 
    "KNOWLEDGE_SYNTH", "MULTI_TURN_CHAT", "LOGIC_PROVING", 
    "SECURITY_AUDIT", "HIVE_MASTERY", "SELF_EVOLUTION"
]

def create_seed(samples_per_cat=10):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(_ROOT, "training_data", "harvest")
    os.makedirs(output_dir, exist_ok=True)
    
    dataset = []
    for cat in CATEGORIES:
        for i in range(samples_per_cat):
            text = f"<|im_start|>system\nYou are Nexus. Category: {cat}<|im_end|>\n<|im_start|>user\nInstruction for {cat} task {i}<|im_end|>\n<|im_start|>assistant\nElite response for {cat} involving agentic action {i}.<|im_end|>"
            dataset.append({"category": cat, "text": text})
    
    if not dataset:
        print("ERROR: Dataset is empty.")
        return
            
    output_path = os.path.join(output_dir, "nexus_harvest_100.json")
    with open(output_path, "w") as f:
        json.dump(dataset, f, indent=2)
    
    # Create 200 sample version too
    dataset_200 = dataset * 2
    output_path_200 = os.path.join(output_dir, "nexus_harvest_200.json")
    with open(output_path_200, "w") as f:
        json.dump(dataset_200, f, indent=2)

    print(f"SUCCESS: Seed datasets created at {output_dir}")

if __name__ == "__main__":
    create_seed()
