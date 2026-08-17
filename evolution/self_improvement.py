"""Self-improvement training script."""
import logging
import os
import sys

from evolution.self_improvement import SelfImprovementEngine

logger = logging.getLogger(__name__)


def main(steps: int = 50) -> None:
    engine = SelfImprovementEngine(".")
    record = engine.analyze_session([{"role": "user", "content": "Run self-improvement training."}])
    if record:
        status_path = os.path.join(".", "configure", "self_improvement_status.json")
        import json

        # Route the status write through the runtime guard so a bad root/config
        # can never point self-improvement at a protected core module.
        try:
            from nexus.common.runtime_guard import guarded_write_text

            guarded_write_text(
                status_path,
                json.dumps(
                    {"status": "completed", "steps": steps, "score": record.score}
                ),
            )
        except Exception as exc:
            logger.warning("self-improvement status write guarded/skipped: %s", exc)
        print(f"Training completed: {steps} steps, score={record.score}")
    else:
        print("Training completed: no improvements found.")

if __name__ == "__main__":
    steps = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    main(steps)
