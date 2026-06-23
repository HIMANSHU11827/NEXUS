# Nexus (Boot Loader)

Primary entry point — launches the API server and interactive shell.

**Version:** 1.0.0

## Entry
`powershell
python -m nexus          # Boot loader → API server + Ink CLI
python -m nexus --shell  # Launch NexusShell directly
`

## Components
- __init__.py — oot() function
- Boot sequence: config load → provider init → server start → shell launch
