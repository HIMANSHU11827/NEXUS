---
name: test_mission_nexus_analysis
description: "Execute the TEST_MISSION workflow: locate nexus.py, preview its header, enumerate available skills, and use MoA to explain the NexusLoop‑ModelRouter architecture."
role: Mission Orchestrator
version: 2.0.0
metadata:
  source: NEXUS_SYNTHESIZER
  original_task: "TEST_MISSION: 1. Use 'glob' to find nexus.py. 2. Use 'file_read' to read its first 5 lines. 3. Use 'scan_skills' to list available skills. 4. Use 'moa_solve' to explain the architectural relationship between the NexusLoop and the ModelRouter."
---

# Test Mission Nexus Analysis 🧠

## Procedural Protocol
1. **[Glob Search]**: Use `glob` with pattern `**/nexus.py` to locate the Nexus entry point.  
   ```json
   {
     "action": "glob",
     "params": {
       "pattern": "**/nexus.py"
     }
   }
   ```
2. **[File Preview]**: Use `file_edit` (view) on the discovered path with `view_range: [1,5]` to read the first five lines.  
   ```json
   {
     "action": "file_edit",
     "params": {
       "command": "view",
       "path": "<path_from_step_1>",
       "view_range": [1,5]
     }
   }
   ```
3. **[Skill Inventory]**: Invoke `scan_skills` with no parameters to retrieve the current skill catalogue.  
   ```json
   {
     "action": "scan_skills"
   }
   ```
4. **[Architectural Explanation]**: Call `moa_solve` with prompt:  
   `"Explain the architectural relationship between the NexusLoop and the ModelRouter components in the Nexus system."`  
   ```json
   {
     "action": "moa_solve",
     "params": {
       "prompt": "Explain the architectural relationship between the NexusLoop and the ModelRouter components in the Nexus system."
     }
   }
   ```

## Verification
- Confirm that `glob` returns a path ending in `nexus.py`.  
- Verify that the file preview shows the expected header (shebang, encoding, docstring, imports).  
- Ensure `scan_skills` output lists multiple skill categories (file, web, RAG, etc.).  
- Check that `moa_solve` returns a coherent description distinguishing NexusLoop (orchestration cycle) from ModelRouter (expert model selection within MixtureOfArchitects).  

Upon successful completion of all four steps, the mission is complete. Sir, we have finished this task. What is our next objective?  
TASK_COMPLETE