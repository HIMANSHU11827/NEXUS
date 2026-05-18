import os
import re
import time
import logging
from typing import List, Dict, Any, Optional, Iterator, Tuple

try:
    import torch
    # Verify torch actually works (handles cases like WinError 1455)
    _test = torch.tensor([1.0])
    import torch.nn as nn
    from transformers import AutoTokenizer, AutoModelForCausalLM, TextIteratorStreamer, logging as transformers_logging
    transformers_logging.set_verbosity_error()
    _BASE_MODULE = nn.Module
    _TORCH_AVAILABLE = True
except Exception as e:
    _TORCH_AVAILABLE = False
    _TORCH_ERROR = str(e)
    torch = None
    nn = None
    AutoTokenizer = None
    AutoModelForCausalLM = None
    TextIteratorStreamer = None
    _BASE_MODULE = object

# ── Dynamic Dependencies
try:
    from core.neural.turbo_quant import TurboQuantEngine
except ImportError:
    TurboQuantEngine = None

try:
    from PIL import Image
    import pytesseract
except ImportError:
    pytesseract = None

try:
    from torchvision.models import mobilenet_v3_small
except ImportError:
    mobilenet_v3_small = None

class PromptDistiller:
    """[COGNITIVE_REDUCTION]: Distills massive system prompts for small models."""
    @staticmethod
    def distill(messages: List[Dict[str, str]], limit: int = 1000) -> List[Dict[str, str]]:
        distilled = []
        for m in messages:
            if m["role"] == "system":
                # Keep only the essentials for NANO models.
                content = m["content"]
                essentials = []
                if "[COMMUNICATION_PROTOCOL]" in content:
                    essentials.append("- Respond concisely and honestly as an engineering operator.")
                if "json" in content.lower():
                    essentials.append("- Output JSON for tool calls: ```json {\"action\": \"...\", \"params\": {}} ```")
                if "TASK_COMPLETE" in content:
                    essentials.append("- Say 'TASK_COMPLETE' when finished.")
                
                # If no keywords found, just truncate
                if not essentials:
                    distilled.append({"role": "system", "content": content[:limit]})
                else:
                    distilled.append({"role": "system", "content": "\n".join(essentials)})
            else:
                distilled.append(m)
        return distilled

logger = logging.getLogger("NEXUS_LOCAL_BRAIN")

class TurboLinear(_BASE_MODULE):
    """
    NEXUS TURBO-LINEAR LAYER v1.2
    Vectorized dequantization and weight caching.
    """
    def __init__(self, original_linear: Any, tq_engine: Any):
        super().__init__()
        self.in_features = original_linear.in_features
        self.out_features = original_linear.out_features
        self.tq = tq_engine
        
        # Vectorized Quantization
        self.q_package = self.tq.polar_quantize(original_linear.weight)
        self.bias = original_linear.bias
        self.device = original_linear.weight.device
        self._cached_weights = None

    @property
    def weight(self):
        if self._cached_weights is not None:
             return self._cached_weights
        weight_matrix = self.tq.dequantize(self.q_package, device=str(self.device))
        self._cached_weights = weight_matrix
        return weight_matrix

    def forward(self, x):
        if not torch: return x
        
        weight_matrix = self.weight
            
        if weight_matrix.dtype != x.dtype:
            weight_matrix = weight_matrix.to(x.dtype)
            
        if self.bias is not None and self.bias.dtype != x.dtype:
            self.bias = self.bias.to(x.dtype)
            
        return torch.nn.functional.linear(x, weight_matrix, self.bias)

class NexusLocalBrain:
    """
    Local model runtime.
    Uses a project-local SmolLM2 adapter when available plus optional vision/OCR helpers.
    """
    def __init__(self, root_dir: str):
        self.root = root_dir
        self.model_dir = os.path.join(self.root, "models", "local")
        
        self.tokenizer = None
        self.text_model = None
        self.vision_model = None
        
        self.device = "cuda" if torch and torch.cuda.is_available() else "cpu"
        self.tq = TurboQuantEngine(bits=4) if TurboQuantEngine else None
        self.is_turbo = False
        self.logger = logger
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            # ⚡ [SOVEREIGN_FIX]: Pull model path from config
            from core.kernel import get_nexus_kernel
            kernel = get_nexus_kernel(root_dir=self.root)
            config = kernel.config.get_all()
            
            # Optional Transformers runtime. The main local chat path uses LM Studio,
            # but this fallback can load a project-local model directory when present.
            default_path = "models/local/qwen3.5-0.8b-uncensored-opus-distill"
            rel_path = config.get("providers", {}).get("local", {}).get("SOVEREIGN_BRAIN", {}).get("model_path", default_path)
            
            self.model_path = os.path.join(self.root, rel_path)
            
            self._load_models()
            self._loaded = True

    def turbo_charge(self):
        """
        [v20.0 GOOGLE_TURBO_QUANT]: Extreme resource reduction.
        Applies PolarQuant + QJL (Quantized Johnson-Lindenstrauss) to all linear layers.
        """
        if not self.text_model or self.is_turbo: 
            return
            
        logger.info("[*] Engaging TurboQuant v1.2...")
        
        # 1. Precision Management
        if "cuda" in str(self.device):
            self.text_model.half() # Move to FP16 for NVIDIA
        else:
            self.text_model.to(torch.float32) # Stable for CPU

        # 2. Layer Patching (PolarQuant)
        if self.tq:
            count = 0
            for name, module in self.text_model.named_modules():
                if isinstance(module, torch.nn.Linear):
                    # Patching linear layers with TurboLinear for 4-bit weights
                    parent_name = ".".join(name.split(".")[:-1])
                    child_name = name.split(".")[-1]
                    if parent_name:
                        parent = self.text_model.get_submodule(parent_name)
                        setattr(parent, child_name, TurboLinear(module, self.tq))
                    else:
                        # Root module is linear (unlikely but possible)
                        self.text_model = TurboLinear(module, self.tq)
                    count += 1
            logger.info(f"[+] TurboQuant: Patched {count} linear layers.")

        self.is_turbo = True
        self.text_model.to(self.device)


    def get_resource_usage(self) -> Dict[str, Any]:
        """Returns the current neural resource footprint."""
        import psutil
        process = psutil.Process(os.getpid())
        mem_mb = process.memory_info().rss / (1024 * 1024)
        return {
            "model_loaded": self._loaded,
            "turbo_active": self.is_turbo,
            "device": self.device,
            "memory_usage_mb": round(mem_mb, 2),
            "engine": "TurboQuant v1.0 (Google Research inspired)"
        }

    def _load_models(self):
        try:
            if not _TORCH_AVAILABLE:
                logger.error(f"[CRITICAL]: Torch or Transformers not available. Error: {_TORCH_ERROR}")
                return

            target_path = self.model_path
            
            if not os.path.exists(target_path):
                logger.error(f"[LOCAL_MODEL_MISSING]: Model missing at {target_path}. Please run the model download/setup script.")
                return
            
            if target_path:
                logger.info(f"[*] Loading Local Brain from {target_path}...")
                
                # ⚡ [BOOT_FIX]: Ensure Windows paths don't trigger HuggingFace RepoID validation errors
                load_kwargs = {"trust_remote_code": True}
                if os.path.isdir(target_path):
                    load_kwargs["local_files_only"] = True
                    # Use forward slashes to prevent escape character issues in some libraries
                    target_path = target_path.replace("\\", "/")

                self.tokenizer = AutoTokenizer.from_pretrained(target_path, **load_kwargs)
                
                # Check for LoRA Adapter
                is_adapter = os.path.exists(os.path.join(target_path, "adapter_config.json"))
                
                if is_adapter:
                    logger.info("[*] LoRA Adapter detected. Loading base model...")
                    from peft import PeftModel
                    # We need the base model name from the config
                    import json
                    with open(os.path.join(target_path, "adapter_config.json"), "r") as f:
                        config = json.load(f)
                    base_model_path = config.get("base_model_name_or_path", "HuggingFaceTB/SmolLM2-135M-Instruct")
                    
                    base_model = AutoModelForCausalLM.from_pretrained(base_model_path, **load_kwargs).to(self.device)
                    self.text_model = PeftModel.from_pretrained(base_model, target_path).to(self.device)
                else:
                    self.text_model = AutoModelForCausalLM.from_pretrained(target_path, **load_kwargs).to(self.device)
                    
                logger.info(f"[+] Text Model Loaded on {self.device}.")
            
            # Load Vision if requested weight exists
            mobile_path = os.path.join(self.model_dir, "mobilenet", "mobilenet_v3_small.pth")
            if mobilenet_v3_small and os.path.exists(mobile_path):
                self.vision_model = mobilenet_v3_small()
                self.vision_model.load_state_dict(torch.load(mobile_path, map_location=self.device))
                self.vision_model.to(self.device).eval()
                logger.info("[+] Vision Model Loaded.")

            # OCR Status
            if pytesseract:
                try:
                    pytesseract.get_tesseract_version()
                    logger.info("[+] OCR Engine: ACTIVE.")
                except:
                    pass

        except Exception as e:
            logger.error(f"[BRAIN_SYNC_ERROR]: Failed to load local neural path '{target_path}': {e}")
            self._loaded = False 

    def _clean_output(self, text: str) -> str:
        """[NEURAL_FILTRATION]: Removes ASCII garbage, repetitions, and hallucinations."""
        if not text: return ""
        
        # 1. Remove repeated characters (e.g., -------- or =======)
        text = re.sub(r'([=\-\._]{10,})', r'\1'[:3], text)
        
        # 2. Remove common hallucination markers
        for marker in ["User:", "Master:", "assistant:", "<|im_start|>", "<|im_end|>", "### Response"]:
            if marker in text: text = text.split(marker)[0].strip()
            
        # 3. Detect "Entropy Explosion" (too many special chars)
        special_chars = sum(1 for c in text if not c.isalnum() and not c.isspace())
        if len(text) > 50 and special_chars / len(text) > 0.4:
            return "[NEURAL_ERROR]: Output entropy too high. Retrying with different temperature..."
            
        return text.strip()

    def generate(self, prompt: str = "", system_prompt: Optional[str] = None, messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        self._ensure_loaded()
        if not self.text_model: return "[ERROR]: Brain is not responsive."
            
        kwargs.setdefault("pad_token_id", self.tokenizer.eos_token_id)
        kwargs.setdefault("max_new_tokens", 512) 
        kwargs.setdefault("repetition_penalty", 1.15)
        kwargs.setdefault("do_sample", True)
        kwargs.setdefault("temperature", 0.4)
        kwargs.setdefault("top_p", 0.85)
        
        # 🛠️ NATIVE TEMPLATE: Use the model's own preferred formatting
        try:
            if messages:
                # Reduce context for small local models.
                messages = PromptDistiller.distill(messages)
                formatted = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            else:
                prompt_msgs = [
                    {"role": "system", "content": system_prompt or "You are Nexus."},
                    {"role": "user", "content": prompt}
                ]
                prompt_msgs = PromptDistiller.distill(prompt_msgs)
                formatted = self.tokenizer.apply_chat_template(prompt_msgs, tokenize=False, add_generation_prompt=True)
        except:
            # Fallback for models without chat templates
            if messages:
                formatted = "\n".join([f"{m['role']}: {m['content']}" for m in messages]) + "\nassistant:"
            else:
                formatted = prompt

        inputs = self.tokenizer(formatted, return_tensors="pt").to(self.device)
        
        with torch.no_grad():
            outputs = self.text_model.generate(**inputs, **kwargs)
        
        # DEBUG
        # print(f"DEBUG: Input length: {inputs.input_ids.shape[-1]}")
        # print(f"DEBUG: Output length: {outputs.shape[-1]}")
        
        # Only decode the newly generated tokens
        new_tokens = outputs[0][inputs.input_ids.shape[-1]:]
        res = self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
        
        return self._clean_output(res)

    def stream_generate(self, prompt: str = "", system_prompt: Optional[str] = None, messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        self._ensure_loaded()
        if not self.text_model:
            yield "[ERROR]: Brain Offline."
            return

        # 🛠️ NATIVE TEMPLATE: Use the model's own preferred formatting
        try:
            if messages:
                # Reduce context for small local models.
                messages = PromptDistiller.distill(messages)
                formatted = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            else:
                prompt_msgs = [
                    {"role": "system", "content": system_prompt or "You are Nexus."},
                    {"role": "user", "content": prompt}
                ]
                prompt_msgs = PromptDistiller.distill(prompt_msgs)
                formatted = self.tokenizer.apply_chat_template(prompt_msgs, tokenize=False, add_generation_prompt=True)
        except:
            # Fallback for models without chat templates
            if messages:
                formatted = "\n".join([f"{m['role']}: {m['content']}" for m in messages]) + "\nassistant:"
            else:
                formatted = prompt

        inputs = self.tokenizer(formatted, return_tensors="pt").to(self.device)
        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)
        
        kwargs.setdefault("max_new_tokens", 512)
        kwargs.setdefault("pad_token_id", self.tokenizer.eos_token_id)
        kwargs.setdefault("eos_token_id", self.tokenizer.eos_token_id)
        kwargs.setdefault("repetition_penalty", 1.2)
        kwargs.setdefault("no_repeat_ngram_size", 3)
        kwargs.setdefault("do_sample", False)
        kwargs.setdefault("temperature", 0.1)
        kwargs.setdefault("top_p", 1.0)
        kwargs["streamer"] = streamer
        
        import threading
        logger.info(f"[*] Starting generation thread with device: {self.device}...")
        try:
            generation_thread = threading.Thread(target=self.text_model.generate, kwargs={**inputs, **kwargs})
            generation_thread.start()
            logger.info("[*] Generation thread started. Waiting for chunks...")

            for chunk in streamer:
                # logger.info(f"[*] Received chunk: {repr(chunk)}")
                if "<|im_end|>" in chunk or "Nexus Assistant:" in chunk: break
                yield chunk
            logger.info("[*] Streamer finished.")
        except Exception as e:
            logger.warning(f"Threading failed, falling back to sync generation: {e}")
            with torch.no_grad():
                outputs = self.text_model.generate(**inputs, **kwargs)
                new_tokens = outputs[0][inputs.input_ids.shape[-1]:]
                yield self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    def scan_image(self, image_path: str) -> dict:
        result = {"text": "", "objects": None}
        if not os.path.exists(image_path) or not pytesseract: return result
        try:
            result["text"] = pytesseract.image_to_string(Image.open(image_path))
        except Exception as e: 
            logger.warning(f"OCR Scan failed: {e}")
        return result

    def fine_tune_on_repo(self):
        import subprocess
        import sys
        
        script_path = os.path.join(self.root, "scripts", "fine_tune_local.py")
        if not os.path.exists(script_path): return False, "Calibration script missing."
        try:
            process = subprocess.Popen([sys.executable, script_path], cwd=self.root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, f"Calibration mission initiated in background (PID: {process.pid})."
        except Exception as e:
            return False, str(e)

if __name__ == "__main__":
    # Test
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    brain = NexusLocalBrain(_root)
    print(brain.generate("Status of nexus core is"))
