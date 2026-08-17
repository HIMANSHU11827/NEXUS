import logging
import threading
from typing import Optional

from models.providers.core.heal_tools import call_repair_tool, init_heal_tools

logger = logging.getLogger("NEXUS_LOCAL_BRAIN")

_HEAL_INTERVAL = 60
_heal_thread: Optional[threading.Thread] = None
_heal_stop = threading.Event()


def heal_round():
    from models.providers.core.profiles import load_profile_store
    store = load_profile_store()
    store.clear_expired_cooldowns()

    call_repair_tool("refresh_oauth")
    call_repair_tool("check_local")


def _heal_loop():
    logger.info("[AUTO-HEAL] Monitor started")
    init_heal_tools()
    while not _heal_stop.is_set():
        try:
            heal_round()
        except Exception as e:
            logger.debug(f"[AUTO-HEAL] Round failed: {e}")
        _heal_stop.wait(_HEAL_INTERVAL)
    logger.info("[AUTO-HEAL] Monitor stopped")


def start_auto_heal():
    global _heal_thread
    if _heal_thread and _heal_thread.is_alive():
        return
    _heal_stop.clear()
    _heal_thread = threading.Thread(target=_heal_loop, daemon=True, name="auto-heal")
    _heal_thread.start()


def stop_auto_heal():
    _heal_stop.set()
