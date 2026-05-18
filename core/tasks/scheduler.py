import asyncio
import json
import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable

logger = logging.getLogger(__name__)

class NexusTaskScheduler:
    """
    NEXUS Task Scheduler (Cron Engine).
    Allows scheduling agentic tasks for future execution.
    """
    
    def __init__(self, loop_runner: Callable[[str], Any]):
        self.loop_runner = loop_runner
        self.scheduled_tasks = []
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self._thread.start()

    def _run_scheduler(self):
        while not self._stop_event.is_set():
            now = time.time()
            to_run = [t for t in self.scheduled_tasks if t["run_at"] <= now and not t["executed"]]
            
            for task in to_run:
                logger.info(f"⏰ [SCHEDULER]: Executing task '{task['name']}'")
                try:
                    self.loop_runner(task["task_desc"])
                    task["executed"] = True
                except Exception as e:
                    logger.error(f"❌ [SCHEDULER]: Task '{task['name']}' failed: {e}")
            
            # Cleanup
            self.scheduled_tasks = [t for t in self.scheduled_tasks if not t["executed"]]
            time.sleep(10) # Check every 10 seconds

    def schedule(self, name: str, task_desc: str, delay_seconds: int):
        run_at = time.time() + delay_seconds
        self.scheduled_tasks.append({
            "name": name,
            "task_desc": task_desc,
            "run_at": run_at,
            "executed": False,
            "scheduled_time": datetime.now().isoformat()
        })
        return f"✅ [SCHEDULER]: Task '{name}' scheduled for execution in {delay_seconds} seconds."

    def list_tasks(self) -> List[Dict[str, Any]]:
        return self.scheduled_tasks
