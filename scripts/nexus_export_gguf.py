
import os
import subprocess
import sys
import logging

# 🌌 [NEXUS_EXPORT_PROTOCOL]: SafeTensors -> GGUF Transition
# Designed for the local-first sovereign workflow.

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NEXUS_EXPORT")

def merge_adapter(model_dir: str):
    """Fuses LoRA adapter weights into the base model for GGUF compatibility."""
    try:
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch
        import json
        
        logger.info("[*] GGUF_EXPORT: Merging LoRA weights...")
        
        with open(os.path.join(model_dir, "adapter_config.json"), "r") as f:
            config = json.load(f)
        base_model_path = config.get("base_model_name_or_path", "HuggingFaceTB/SmolLM2-135M-Instruct")
        
        base_model = AutoModelForCausalLM.from_pretrained(base_model_path, dtype=torch.float16)
        peft_model = PeftModel.from_pretrained(base_model, model_dir)
        
        merged_model = peft_model.merge_and_unload()
        
        temp_merged_dir = model_dir + "_merged"
        os.makedirs(temp_merged_dir, exist_ok=True)
        merged_model.save_pretrained(temp_merged_dir)
        
        tokenizer = AutoTokenizer.from_pretrained(model_dir)
        tokenizer.save_pretrained(temp_merged_dir)
        
        logger.info(f"[+] GGUF_EXPORT: Merge complete. Temporary merged model at {temp_merged_dir}")
        return temp_merged_dir
    except Exception as e:
        logger.error(f"[-] GGUF_EXPORT: Merging failed: {e}")
        return None

def export_to_gguf(model_dir: str, output_name: str = "nexus_model.gguf"):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Check if it's an adapter
    if os.path.exists(os.path.join(model_dir, "adapter_config.json")):
        model_dir = merge_adapter(model_dir)
        if not model_dir: return False

    # 🔍 Find llama.cpp conversion script
    convert_script = os.path.join(_ROOT, "vendor", "llama.cpp", "convert_hf_to_gguf.py")
    if not os.path.exists(convert_script):
        alt_script = os.path.join(_ROOT, "llama.cpp", "convert_hf_to_gguf.py")
        if os.path.exists(alt_script):
            convert_script = alt_script
        else:
            logger.error("[-] GGUF_EXPORT: 'convert_hf_to_gguf.py' not found. Please clone llama.cpp into 'vendor/llama.cpp'.")
            return False

    output_path = os.path.join(_ROOT, "models", "local", output_name)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    logger.info(f"[*] GGUF_EXPORT: Starting conversion of {model_dir}...")
    
    # CMD Construction
    cmd = [
        sys.executable, convert_script,
        model_dir,
        "--outfile", output_path,
        "--outtype", "q8_0" 
    ]

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            print(f"  [LLAMA_CPP]: {line.strip()}")
        process.wait()
        
        if process.returncode == 0:
            logger.info(f"[+] GGUF_EXPORT: SUCCESS. Model saved at {output_path}")
            # Cleanup temp dir if it was created
            if model_dir.endswith("_merged"):
                import shutil
                # shutil.rmtree(model_dir) # Keep for now for debugging if needed
                pass
            return True
        else:
            logger.error(f"[-] GGUF_EXPORT: Conversion failed with return code {process.returncode}")
            return False
    except Exception as e:
        logger.error(f"[-] GGUF_EXPORT: Critical failure during execution: {e}")
        return False

if __name__ == "__main__":
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_model = os.path.join(_ROOT, "models", "local", "smollm2-135m-nexus-agent")
    
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        target = default_model
        
    export_to_gguf(target)
