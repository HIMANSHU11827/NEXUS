# hive Tool
**Version:** 2.0.0

Spawn dedicated sub-agents for complex multi-step tasks. Each sub-agent runs as an isolated LLM call with a specific persona.

## Parameters
- `task` (string, required): The task for the sub-agent to complete
- `persona` (string, optional, default="WORKER"): WORKER|RESEARCHER|ENGINEER|CRITIC|PLANNER
- `mode` (string, optional, default="single"): single|parallel|hive
- `sub_tasks` (array, optional): List of sub-tasks for parallel/hive mode
