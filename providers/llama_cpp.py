from typing import Dict, Any, Optional, List, Iterator
from providers.base import NexusBaseProvider
import os
import logging

logger = logging.getLogger("NEXUS_LLAMA_CPP")

class LlamaCPPProvider(NexusBaseProvider):
    """
    NEXUS NATIVE GGUF PROVIDER (LLAMA-CPP)
    Direct binding to llama.cpp for maximum local performance.
    """
    
    def __init__(self):
        # We need to load config first to get ctx_size and gpu_layers
        self.config_data = {}
        try:
            from config_loader import NexusConfigLoader
            loader = NexusConfigLoader()
            self.config_data = loader.get_provider_config("llama_cpp")
        except Exception: 
            pass
            
        super().__init__("llama_cpp", "")
        self.llm = None
        self._load_llm()

    def _load_llm(self):
        try:
            from llama_cpp import Llama
            
            # 🔍 [PATH_RESOLUTION]: Find the most relevant GGUF
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            local_models_dir = os.path.join(root, "models", "local")
            
            target_path = None
            
            # Priority 1: Check config override
            if self.model and os.path.exists(self.model) and self.model.endswith(".gguf"):
                target_path = self.model
            
            # Priority 2: Search models/local recursively for .gguf files
            if not target_path:
                for r, d, f in os.walk(local_models_dir):
                    for file in f:
                        if file.endswith(".gguf"):
                            target_path = os.path.join(r, file)
                            break
                    if target_path: break

            if target_path:
                logger.info(f"[*] NEXUS_GGUF_ENGINE: Initializing with {target_path}")
                
                # 🚀 [GPU_OPTIMIZATION]: Granular offloading for iGPU + dGPU hybrid setups
                gpu_layers = self.config_data.get("gpu_layers", -1)
                ctx_size = self.config_data.get("ctx_size", 4096)
                main_gpu = self.config_data.get("main_gpu", 0)
                tensor_split = self.config_data.get("tensor_split", None)
                
                self.llm = Llama(
                    model_path=target_path,
                    n_ctx=ctx_size,
                    n_gpu_layers=gpu_layers,
                    main_gpu=main_gpu,
                    tensor_split=tensor_split,
                    verbose=False
                )
                logger.info(f"[+] Llama-CPP: High-Performance Engine Online (GPU Layers: {gpu_layers}).")
            else:
                logger.warning("[-] Llama-CPP: No GGUF model found in models/local/. Local brain may be offline.")
        except ImportError:
            logger.error("[-] Llama-CPP: 'llama-cpp-python' missing. Run 'pip install llama-cpp-python' to enable local GGUF.")
        except Exception as e:
            logger.error(f"[-] Llama-CPP: Load failed: {e}")

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        if not self.llm: return "Error: Llama-CPP not initialized or model missing."
        
        # 🔱 [CHATML_PROTOCOL]: Force alignment with training standard
        if messages:
            formatted_prompt = ""
            for msg in messages:
                role = msg["role"]
                content = msg["content"]
                formatted_prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
            formatted_prompt += "<|im_start|>assistant\n"
            
            try:
                response = self.llm(formatted_prompt, stop=["<|im_end|>", "TASK_COMPLETE"], max_tokens=1024)
                return response["choices"][0]["text"].strip()
            except Exception as e:
                return f"Error in Llama-CPP generate (ChatML): {e}"
        
        # Fallback to simple logic if no messages
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        try:
            response = self.llm.create_chat_completion(messages=msgs, stream=False)
            return response["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Error in Llama-CPP generate: {e}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        if not self.llm:
            yield "Error: Llama-CPP not initialized."
            return
            
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        try:
            stream = self.llm.create_chat_completion(messages=msgs, stream=True)
            for chunk in stream:
                delta = chunk["choices"][0].get("delta", {})
                if "content" in delta:
                    yield delta["content"]
        except Exception as e:
            yield f"Error in Llama-CPP stream: {e}"
