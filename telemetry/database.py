import logging

logger = logging.getLogger("NEXUS_TELEMETRY")

class NexusTelemetryDB:
    def __init__(self):
        logger.info("NexusTelemetryDB initialized (stub — no telemetry storage)")

    def log_tool_call(self, tool: str, params: dict, result: str, duration: float):
        logger.debug(f"NexusTelemetryDB.log_tool_call({tool}) — stub, no-op")

    def log_error(self, error: str, context: dict):
        logger.debug(f"NexusTelemetryDB.log_error — stub, no-op")
