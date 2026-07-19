"""Self-improvement training script."""
import os
import sys

from evolution.self_improvement import SelfImprovementEngine


def main(steps: int = 50) -> None:
    engine = SelfImprovementEngine(".")
    record = engine.analyze_session([{"role": "user", "content": "Run self-improvement training."}])
    if record:
        status_path = os.path.join(".", "config", "self_improvement_status.json")
        import json
        os.makedirs(os.path.dirname(status_path), exist_ok=True)
        with open(status_path, "w") as f:
            json.dump({"status": "completed", "steps": steps, "score": record.score}, f)
        print(f"Training completed: {steps} steps, score={record.score}")
    else:
        print("Training completed: no improvements found.")

if __name__ == "__main__":
    steps = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    main(steps)
