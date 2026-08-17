# Planning Tool

Maintains a single truthful, task-specific `todo.md` plan — create, add, complete, and update checklist items.

**Version:** 2.0.0

## Behavior
- `create` — builds the plan from the LLM-provided `plan_spec` JSON (simple or phased); a missing/invalid spec is rejected, never replaced with a generic template
- `add` — appends a new item (into a specific phase when the plan is phased)
- `complete` — marks an item `[x]`
- `update` — replaces `old_text` with `new_text` inside the plan
- Every checklist line carries a stable `task_<hex>` ID that survives edits
- Each mutation syncs to `nexus.control_plane.create_checklist_plan` and `nexus.work_items.reconcile_checklist_work_item`

See `planning.md` for the full parameter reference.
