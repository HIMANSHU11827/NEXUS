import os
from huggingface_hub import snapshot_download

def download_base():
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target = os.path.join(_ROOT, "models", "local", "smollm2-135m-base")
    os.makedirs(target, exist_ok=True)
    
    print(f"[*] Downloading Base Brain (SmolLM2-135M) to {target}...")
    snapshot_download(
        repo_id="HuggingFaceTB/SmolLM2-135M-Instruct",
        local_dir=target,
        local_dir_use_symlinks=False
    )
    print(f"[✅] Base Brain secured at {target}")

if __name__ == "__main__":
    download_base()
