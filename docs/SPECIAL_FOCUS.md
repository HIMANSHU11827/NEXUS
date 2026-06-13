# Special Focus: Repair Weak Systems

Fix all fake, weak, shallow, or broken systems from the previous audit.

## 1. Hive Workers

The Hive system must be real local worker orchestration, not a subprocess/logging illusion.

Required capabilities:
- task planner
- role-based Hive workers
- shared state
- task queue
- Hive worker communication
- progress tracking
- cancellation
- retries
- result merging
- logs/artifacts
- failure recovery

## 2. World Simulation

If world simulation is only a static string, remove the claim or implement useful simulation/planning.

Required capabilities:
- environment state
- action prediction
- risk estimation
- planning outcomes
- scenario testing
- task impact analysis

## 3. Safety / Command Execution

NEXUS is designed for direct execution without approval popups, but it still needs safety-by-design.

Required capabilities:
- command risk scoring
- dangerous command detection
- path protection
- rollback before destructive actions
- timeout handling
- process kill support
- audit logs
- safe defaults

Do not add annoying approval prompts unless optional.

## 4. Provider System

Provider support must be real, observable, and resilient.

Required capabilities:
- provider health checks
- API key validation
- fallback routing
- latency tracking
- model capability registry
- error normalization
- retry logic
- streaming consistency
- local/cloud provider profiles

## 5. RAG / Memory

RAG must be reliable and testable.

Required capabilities:
- persistent document storage
- automatic index rebuild
- hybrid search
- vector + keyword retrieval
- chunking
- metadata
- ranking
- project memory
- memory cleanup
- retrieval tests

## 6. Tests

Stop patching around broken source code. Fix the real code instead.

Required capabilities:
- remove duplicate tests
- remove stale tests
- add real unit tests
- add integration tests
- add CLI/backend/gui tests
- add regression tests
- make pytest reliable
- create CI test pipeline

## 7. Packaging

Packaging must include only real source and necessary runtime files.

Required capabilities:
- exclude models, caches, temp repos, logs, gui build files, and tests when not needed
- include only real source files
- clean pyproject
- add .gitignore
- add release structure
- reduce package size

## 8. gui Security

gui security must be treated as real application security.

Required capabilities:
- remove wildcard CORS
- sanitize session IDs
- sanitize upload filenames
- block path traversal
- protect config writes
- add auth or local-only mode
- validate all API inputs
- secure file uploads
- add rate limits
- add logs

## Operating Rule

For each area:
- verify the current implementation from actual code
- classify it as fake, weak, broken, or real
- explain exactly why
- fix or upgrade it
- test it
- show before vs after results

Do not just rename things. Do real engineering fixes. Remove fake hype if the system is not real. Make the project honest, stronger, safer, and more production-grade.
