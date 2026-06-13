import requests
import json
import yaml
import os
from typing import Dict, Any, Optional
from config_loader import NexusConfigLoader


class LMStudioAutoProvider:
    """
    NEXUS AUTO-DISCOVERY PROVIDER (LM STUDIO)
    Now fully linked to the MASTER nexus_config.yaml.
    It will automatically find your 'Gemma-3-270m-it-qat'
    or whatever you have running on port 1234.
    """

    def __init__(self, port: Optional[int] = None):
        self.config_loader = NexusConfigLoader()
        self.config = self.config_loader.get_provider_config("local", "lm_studio")
        self.port = port or 1234
        self.endpoint = f"http://localhost:{self.port}/v1"
        self.active_model = self.config.get("default_model", "unknown")
        self.is_running = False

    def auto_scan(self):
        """Pings LM Studio and assigns the running model ID to this provider."""
        try:
            response = requests.get(f"{self.endpoint}/models")
            if response.status_code == 200:
                models = response.json().get("data", [])
                if models:
                    self.active_model = models[0]["id"]
                    self.is_running = True
                    # Optional: Update the YAML file if the model changed
                    print(f"[*] 🦀 Auto-Detected Local Model: {self.active_model}")
                    return True
            return False
        except (ConnectionError, TimeoutError, requests.RequestException):
            self.is_running = False
            return False

    def generate(self, prompt: str = '', system_prompt: str = "") -> str:
        """Sends a generation request to the auto-detected model."""
        if not self.is_running:
            self.auto_scan()

        payload = {
            "model": self.active_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        try:
            response = requests.post(f"{self.endpoint}/chat/completions", json=payload)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            return f"Error: LM Studio returned {response.status_code}"
        except Exception as e:
            return f"Error: Self-Detection failed or model unloaded. {str(e)}"


if __name__ == "__main__":
    scanner = LMStudioAutoProvider()
    if scanner.auto_scan():
        print(f"Connecting to: {scanner.active_model}")
        # print(scanner.generate("Hello Gemma!"))
    else:
        print("LM Studio is not running on port 1234.")
