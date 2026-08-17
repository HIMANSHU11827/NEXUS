# Task Tool

Checklist task management on the canonical `todo.md` plan — which checklist item is pending or complete.

**Version:** 2.1.0

## Behavior
- Manages the same `todo.md` file and stable task IDs as the `planning` tool
- Actions: list, create, status/get, update, delete
- Status enum: `pending` | `in_progress` | `completed`
- Syncs changes to `create_checklist_plan` + `reconcile_checklist_work_item`

See `task.md` for parameters.
