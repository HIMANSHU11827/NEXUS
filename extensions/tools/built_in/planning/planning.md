# Planning Tool
**Version:** 2.0.0

Create and maintain one truthful, task-specific plan. The canonical file is
`workspace/todo.md` when the workspace directory exists; otherwise it is
`todo.md` at the project root.

## Parameters
- `goal` (string, required for create): Task or goal to plan
- `plan_spec` (object/string, optional): LLM-generated JSON plan — `{"plan_type": "simple", "steps": ["..."]}` or `{"plan_type": "phased", "phases": [{"title": "...", "subgoals": ["..."]}]}`
- `action` (string, optional, default=create): create | add | complete | update
- `item` (string, required for add/complete): Todo item text
- `phase` (string, optional): Phase name for `add` on phased plans
- `old_text` (string, required for update): Existing text to replace
- `new_text` (string, required for update): Replacement text

## Output
Returns the full updated `todo.md` plan. Checklist items keep stable `task_<hex>` IDs, and each change is synced to the durable checklist plan and work items via `create_checklist_plan` + `reconcile_checklist_work_item`.
