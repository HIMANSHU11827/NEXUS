# workflows — Mission/phase workflow model and planning

## Authoritative implementation
- `workflows/NEXUS_WORKFLOW_MODEL.md` — mission/phase/event workflow model doc (moved from `docs/`)
- `extensions/tools/built_in/planning/scripts/planning.py` — `PlanningTool` ("planning" tool); canonical plan file is `.nexus/workspace/todo.md`, serialized via sqlite plan-transaction locks
- `src/nexus/control_plane.py` — durable Task → PlanVersion → Step control-plane records: plan/step status machines, transition tables, atomic JSON persistence
- `src/nexus/work_items.py` — durable work-item state machine (`draft → planned → approved → running → …`), projected from run events

## Why this directory exists
This is the approved home for the workflow model and planning subsystem. The model document was moved here from `docs/` per the restructure allowlist; the implementations live in `extensions/tools/built_in/planning/` and the `src/nexus` control-plane modules.

## Notes
`todo.md` is the editable compatibility view; `control_plane.py` stores runtime facts a checklist cannot express (dependencies, attempts, verification evidence), and `work_items.py` owns the event-projected work-item lifecycle.