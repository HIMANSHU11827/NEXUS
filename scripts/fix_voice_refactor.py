#!/usr/bin/env python3
"""Refactor: extract voice session logic into a helper and always create fresh session."""
FILE = 'cli/nexus-cli.tsx'

with open(FILE, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
original_count = len(lines)

# === STEP 1: Insert helper function before the App component ===
# Find `const App = () => {`
app_line = None
for i, line in enumerate(lines):
    if line.strip() == 'const App = () => {':
        app_line = i
        break

if app_line is None:
    print("ERROR: Could not find 'const App = () => {'")
    exit(1)

helper_block = [
    "const ensureFreshVoiceSession = async (",
    "    sessionId: string,",
    "    apiJson: (endpoint: string, init?: RequestInit) => Promise<any>,",
    "    setSessionId: (id: string) => void,",
    "    setHistory: (fn: any) => void",
    "): Promise<string> => {",
    "    // Always create a fresh session when starting voice to avoid old history",
    "    try {",
    "        const created = await apiJson('/sessions/new', {method: 'POST'});",
    "        if (created && created.id) {",
    "            setSessionId(created.id);",
    "            setHistory([]);",
    "            return created.id;",
    "        }",
    "    } catch {",
    "        // Fall back to current session if new session creation fails",
    "    }",
    "    setHistory([]);",
    "    return sessionId;",
    "};",
    "",
    "",
]

lines = lines[:app_line] + helper_block + lines[app_line:]
helper_shift = len(helper_block)
print(f"STEP 1: Inserted helper function before App component (shifted by {helper_shift} lines)")

# === STEP 2: Replace the first duplicated block (defaultMode) with helper call ===
# Find the first "Auto-create a fresh session" comment
first_block_start = None
for i, line in enumerate(lines):
    if 'Auto-create a fresh session when starting voice to avoid old history' in line:
        first_block_start = i
        break

if first_block_start is None:
    print("ERROR: Could not find first fresh-session block")
    exit(1)

# Find the end of this block (the empty line before pushCommand starting voice)
first_block_end = None
for i in range(first_block_start, first_block_start + 25):
    if i < len(lines) and 'pushCommand(`🎙️ starting voice (${defaultMode})' in lines[i]:
        first_block_end = i
        break

if first_block_end is None:
    print("ERROR: Could not find end of first fresh-session block")
    exit(1)

# Get the indentation of the block
indent = lines[first_block_start].split('//')[0]

# Replace the entire block with a helper call
replacement_1 = [
    f"{indent}// Create a fresh session for clean voice experience",
    f"{indent}const voiceSessionId = await ensureFreshVoiceSession(",
    f"{indent}    sessionId, apiJson, setSessionId, setHistory",
    f"{indent});",
    f"",
]

lines = lines[:first_block_start] + replacement_1 + lines[first_block_end:]
second_shift = len(replacement_1) - (first_block_end - first_block_start)
print(f"STEP 2: Replaced first duplicated block with helper call")

# === STEP 3: Replace the second duplicated block (sub mode) with helper call ===
# Find the second "Auto-create a fresh session" comment
second_block_start = None
for i, line in enumerate(lines):
    if 'Auto-create a fresh session when starting voice to avoid old history' in line:
        second_block_start = i
        break

if second_block_start is None:
    print("ERROR: Could not find second fresh-session block")
    exit(1)

# Find the end of this block
second_block_end = None
for i in range(second_block_start, second_block_start + 25):
    if i < len(lines) and 'pushCommand(`🎙️ starting voice (${sub})' in lines[i]:
        second_block_end = i
        break

if second_block_end is None:
    print("ERROR: Could not find end of second fresh-session block")
    exit(1)

indent2 = lines[second_block_start].split('//')[0]

replacement_2 = [
    f"{indent2}// Create a fresh session for clean voice experience",
    f"{indent2}const voiceSessionId = await ensureFreshVoiceSession(",
    f"{indent2}    sessionId, apiJson, setSessionId, setHistory",
    f"{indent2});",
    f"",
]

lines = lines[:second_block_start] + replacement_2 + lines[second_block_end:]
print(f"STEP 3: Replaced second duplicated block with helper call")

# Write the result
new_content = '\n'.join(lines)
with open(FILE, 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f"Original lines: {original_count}, New lines: {len(lines)}")
print("Done!")
