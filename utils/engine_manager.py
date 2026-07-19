"""Engine manager stubs for llama.cpp compilation status."""

import logging

logger = logging.getLogger("nexus.engine_manager")

STATUS_PATH = ""

def get_engine_status() -> dict:
    return {"compiled": False, "engine": "llama.cpp", "status": "not_compiled"}

def load_or_create_config() -> dict:
    return {"llama_cpp_params": {}, "system": {}, "default_model": ""}

def save_config(config: dict) -> None:
    logger.debug("save_config (stub) — no-op")

def reload_engine() -> bool:
    return True
