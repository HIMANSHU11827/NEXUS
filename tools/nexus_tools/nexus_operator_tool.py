import os
import time
import base64
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image
import pyautogui
from tools.nexus_tools.base_tool import BaseTool, ToolResult
from tools.nexus_tools.vision.screenshot import capture_screen_with_cursor
from tools.nexus_tools.vision.ocr import get_text_element, get_text_coordinates
from tools.nexus_tools.vision.som import add_labels, get_click_position_in_percent

class NexusGUIOperator(BaseTool):
    """
    NEXUS GUI MATRIX OPERATOR 4.5 (GOD-ARCHITECT)
    Hyper-optimized for speed and reliability. 
    Unified Vision-Grounded Computer Use.
    """

    name = "gui_operate"
    description = (
        "Operate host GUI. Actions: "
        "'click' (x,y), 'write' (text), 'press' (keys), 'scroll' (amount), "
        "'ocr_click' (text), 'capture' (mode), 'get_map' (mode), 'wait' (seconds)."
    )

    # Lazy-loaded vision models
    _yolo_model = None
    _ocr_reader = None

    def __init__(self, root_dir: str):
        self.root = root_dir
        self.mouse_speed = 0.3
        self.temp_dir = os.path.join(self.root, "logs", "gui_temp")
        os.makedirs(self.temp_dir, exist_ok=True)
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.1
        
        self.weights_path = os.path.join(self.root, "tools", "nexus_tools", "weights", "best.pt")
        self.last_screenshot = os.path.join(self.temp_dir, "last_shot.png")

    def _get_yolo(self):
        if NexusGUIOperator._yolo_model is None and os.path.exists(self.weights_path):
            from ultralytics import YOLO
            NexusGUIOperator._yolo_model = YOLO(self.weights_path)
        return NexusGUIOperator._yolo_model

    def _get_ocr(self):
        if NexusGUIOperator._ocr_reader is None:
            import easyocr
            NexusGUIOperator._ocr_reader = easyocr.Reader(['en'], gpu=True)
        return NexusGUIOperator._ocr_reader

    def is_concurrency_safe(self, input_data: Dict[str, Any] = None) -> bool:
        return False

    def execute_action(self, action: str, params: Dict[str, Any]) -> str:
        """Alias for compatibility with Loop Orchestrator."""
        result = self.call(action=action, params=params)
        return str(result)

    def call(self, **kwargs) -> ToolResult:
        action = kwargs.get("action")
        params = kwargs.get("params", {})
        
        try:
            if action == "click":
                return ToolResult(data=self._click(params))
            elif action == "write":
                return ToolResult(data=self._write(params))
            elif action == "press":
                return ToolResult(data=self._press(params))
            elif action == "scroll":
                return ToolResult(data=self._scroll(params))
            elif action == "wait":
                time.sleep(params.get("seconds", 1))
                return ToolResult(data="[NEXUS_GUI]: Wait finished.")
            elif action == "capture":
                return self._capture(params)
            elif action == "get_map":
                return self._get_map(params)
            elif action == "ocr_click":
                return self._ocr_click(params)
            else:
                return ToolResult(error=f"Unsupported action: {action}")
        except Exception as e:
            return ToolResult(error=f"GUI_SYSTEM_ERROR: {str(e)}")

    def _click(self, params: Dict[str, Any]) -> str:
        # Standardizing to 0-100 scale
        x_val = float(params.get("x", 0))
        y_val = float(params.get("y", 0))
        button = params.get("button", "left")
        
        sw, sh = pyautogui.size()
        # Auto-detect scale (0-1 vs 0-100)
        x_pct = x_val / 100.0 if x_val > 1.0 else x_val
        y_pct = y_val / 100.0 if y_val > 1.0 else y_val
        
        x, y = int(sw * x_pct), int(sh * y_pct)
        pyautogui.click(x, y, button=button, duration=self.mouse_speed)
        return f"[NEXUS_GUI]: Interacted {button} at ({x}, {y}) [{int(x_pct*100)}%, {int(y_pct*100)}%]"

    def _write(self, params: Dict[str, Any]) -> str:
        text = params.get("text", "")
        pyautogui.write(text, interval=0.03)
        return f"[NEXUS_GUI]: Input stream sent: '{text[:20]}...'"

    def _press(self, params: Dict[str, Any]) -> str:
        keys = params.get("keys", [])
        if isinstance(keys, str): keys = [keys]
        for key in keys: pyautogui.keyDown(key)
        time.sleep(0.05)
        for key in reversed(keys): pyautogui.keyUp(key)
        return f"[NEXUS_GUI]: Key-sequence executed: {keys}"

    def _scroll(self, params: Dict[str, Any]) -> str:
        amount = int(params.get("amount", 200))
        pyautogui.scroll(amount)
        return f"[NEXUS_GUI]: Viewport scrolled {amount}"

    def _capture(self, params: Dict[str, Any]) -> ToolResult:
        mode = params.get("mode", "standard")
        capture_screen_with_cursor(self.last_screenshot)
        
        with open(self.last_screenshot, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
            
        if mode == "som":
            model = self._get_yolo()
            if model:
                img_b64, _ = add_labels(img_b64, model)
                return ToolResult(data="[NEXUS_GUI]: Grounded vision capture (SoM) ready.", 
                                 new_messages=[{"role": "system", "content": f"[GUI_MATRIX]: Labels applied for precision navigation."}])
            
        return ToolResult(data="[NEXUS_GUI]: Standard vision capture ready.")

    def _get_map(self, params: Dict[str, Any]) -> ToolResult:
        capture_screen_with_cursor(self.last_screenshot)
        sw, sh = pyautogui.size()
        map_data = {"screen_size": {"width": sw, "height": sh}, "text_elements": [], "labeled_objects": []}
        
        # 1. OCR (Text Map)
        try:
            reader = self._get_ocr()
            results = reader.readtext(self.last_screenshot)
            for i, res in enumerate(results):
                coords = get_text_coordinates(results, i, self.last_screenshot)
                map_data["text_elements"].append({"text": res[1], "pct": coords})
        except Exception: pass
        
        # 2. YOLO (Object Map)
        try:
            model = self._get_yolo()
            if model:
                image = Image.open(self.last_screenshot)
                with open(self.last_screenshot, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                _, label_coords = add_labels(b64, model)
                for label, box in label_coords.items():
                    pct = get_click_position_in_percent(box, image.size)
                    map_data["labeled_objects"].append({"id": label, "pct": {"x": pct[0], "y": pct[1]}})
        except Exception: pass
        
        return ToolResult(data=map_data)

    def _ocr_click(self, params: Dict[str, Any]) -> ToolResult:
        text = params.get("text", "")
        if not os.path.exists(self.last_screenshot):
            capture_screen_with_cursor(self.last_screenshot)
        
        reader = self._get_ocr()
        results = reader.readtext(self.last_screenshot)
        idx = get_text_element(results, text, self.last_screenshot)
        coords = get_text_coordinates(results, idx, self.last_screenshot)
        
        self._click({"x": coords['x'], "y": coords['y']})
        return ToolResult(data=f"[NEXUS_GUI]: Target '{text}' found and clicked at {coords}")

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["click", "write", "press", "scroll", "wait", "capture", "ocr_click", "get_map"]},
                    "params": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number", "description": "Horizontal location (0-100)"},
                            "y": {"type": "number", "description": "Vertical location (0-100)"},
                            "text": {"type": "string"},
                            "keys": {"type": "array", "items": {"type": "string"}},
                            "amount": {"type": "integer"},
                            "seconds": {"type": "number"},
                            "mode": {"type": "string", "enum": ["standard", "som"]}
                        }
                    }
                },
                "required": ["action", "params"]
            }
        }
