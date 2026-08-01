"""Enqueue entrypoint for the NEXUS 24/7 queue driver.

    python -m queue.enqueue "build me a REST API"
    python -m queue.enqueue --priority 5 --model gpt-4o "urgent task"
    python -m queue.enqueue --list
"""

from __future__ import annotations

import sys
from typing import Any, List, Optional

from .driver import enqueue_task, get_queue

__all__ = ["enqueue_task", "main"]


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(
        prog="python -m queue.enqueue",
        description="Add a task to the NEXUS durable task queue.",
    )
    p.add_argument("task", nargs="*", help="task description")
    p.add_argument("--priority", type=int, default=0)
    p.add_argument("--provider", type=str, default="")
    p.add_argument("--model", type=str, default="")
    p.add_argument("--voice-mode", type=str, default="text")
    p.add_argument("--max-attempts", type=int, default=None)
    p.add_argument("--db", type=str, default=None)
    p.add_argument("--list", action="store_true", help="show queue state counts")
    args = p.parse_args(argv)

    if args.list:
        print(get_queue(db_path=args.db).list_states())
        return 0

    task_desc = " ".join(args.task).strip()
    if not task_desc:
        p.error("no task text given")

    kwargs: dict[str, Any] = {
        "priority": args.priority,
        "provider": args.provider,
        "model": args.model,
        "voice_mode": args.voice_mode,
        "db_path": args.db,
    }
    if args.max_attempts is not None:
        kwargs["max_attempts"] = args.max_attempts

    task_id = enqueue_task(task_desc, **kwargs)
    print(f"enqueued task {task_id}: {task_desc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
