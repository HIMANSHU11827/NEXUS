"""
NEXUS IMAGE GENERATION TOOL — Generate images using API or local models
Like Hermes image_gen: generates images from text prompts.
"""
import json
import os
import base64
import subprocess
from typing import Any, Dict, Optional
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class ImageGenerateTool(BaseTool):
    """Generate images from text descriptions using local or API-based models."""
    name = "image_generate"
    description = "Generate images from text prompts. Tries local models first (ComfyUI, SD), falls back to API (OpenRouter image models)."
    aliases = ["generate_image", "draw", "create_image"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.output_dir = os.path.join(self.root, "workspace", "images")
        os.makedirs(self.output_dir, exist_ok=True)

    def call(self, prompt: str = "", negative_prompt: str = "", width: int = 512, height: int = 512, count: int = 1) -> ToolResult:
        if not prompt:
            return ToolResult(error="prompt is required")

        try:
            timestamp = str(int(__import__('time').time()))
            results = []

            # Try OpenRouter image generation first
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            if api_key:
                result = self._try_openrouter(prompt, negative_prompt, width, height, count, timestamp)
                if result:
                    results = result

            # If OpenRouter failed, try local
            if not results:
                result = self._try_local(prompt, timestamp)
                if result:
                    results = [result]

            if not results:
                return ToolResult(data=self._prompt_only_fallback(prompt, timestamp))

            output = "### [IMAGE GENERATED]\n\n"
            for r in results:
                output += f"- File: {r['path']}\n"
                output += f"- Prompt: {r['prompt'][:100]}\n"
                output += f"- URL: {r.get('url', 'local file')}\n\n"

            return ToolResult(data=output)

        except Exception as e:
            return ToolResult(error=f"Image generation error: {str(e)}")

    def _try_openrouter(self, prompt, negative_prompt, width, height, count, timestamp):
        """Try image generation via OpenRouter."""
        try:
            import requests

            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            if not api_key:
                return None

            # Try several image models via OpenRouter
            models = [
                "black-forest-labs/flux-schnell",
                "black-forest-labs/flux-dev",
                "stabilityai/stable-diffusion-3.5-large",
                "openai/dall-e-3",
            ]

            for model in models:
                try:
                    resp = requests.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "n": count,
                        },
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        results = []
                        for i, choice in enumerate(data.get("choices", [])):
                            content = choice.get("message", {}).get("content", "")
                            # Check if content contains an image URL (markdown or direct)
                            urls = []
                            if "![" in content:
                                import re
                                urls = re.findall(r'!\[.*?\]\((.*?)\)', content)
                            if not urls:
                                # Maybe it's a direct URL
                                if content.startswith("http"):
                                    urls = [content]
                            
                            for url in urls:
                                fname = f"nexus_img_{timestamp}_{i}.png"
                                fpath = os.path.join(self.output_dir, fname)
                                img_resp = requests.get(url, timeout=30)
                                with open(fpath, "wb") as f:
                                    f.write(img_resp.content)
                                results.append({
                                    "path": fpath,
                                    "prompt": prompt,
                                    "url": url,
                                })
                        
                        if results:
                            return results
                except Exception: 
                    continue

            return None
        except Exception: 
            return None

    def _try_local(self, prompt, timestamp):
        """Try local image generation (Stable Diffusion CLI)."""
        try:
            # Try invoke stable-diffusion or comfy CLI if available
            sd_script = os.path.join(self.root, "scripts", "generate_image.py")
            if os.path.exists(sd_script):
                fname = f"nexus_img_{timestamp}.png"
                fpath = os.path.join(self.output_dir, fname)
                result = subprocess.run(
                    [sd_script, "--prompt", prompt, "--output", fpath],
                    capture_output=True, text=True, timeout=60,
                )
                if os.path.exists(fpath):
                    return {"path": fpath, "prompt": prompt, "url": ""}
            return None
        except Exception: 
            return None

    def _prompt_only_fallback(self, prompt, timestamp):
        """When no image generation is available, save the prompt for later."""
        fname = f"nexus_img_prompt_{timestamp}.txt"
        fpath = os.path.join(self.output_dir, fname)
        with open(fpath, "w") as f:
            f.write(f"Prompt: {prompt}\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write(f"Note: No image model available. Install ComfyUI or configure an API key.\n")
        
        return f"### [IMAGE PROMPT SAVED]\n\nPrompt saved to: {fpath}\n\nNo image generation model available. To enable:\n1. Add OPENROUTER_API_KEY to .env for Flux/DALL-E via API\n2. Install ComfyUI locally for fully offline generation"

    def is_read_only(self, input_data=None):
        return True

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Text description of the image to generate."},
                    "negative_prompt": {"type": "string", "description": "What to avoid in the image."},
                    "width": {"type": "integer", "description": "Image width (default 512)."},
                    "height": {"type": "integer", "description": "Image height (default 512)."},
                    "count": {"type": "integer", "description": "Number of images (default 1)."},
                },
                "required": ["prompt"],
            },
        }
