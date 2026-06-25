#!/usr/bin/env python3
"""Revert: remove ensureFreshVoiceSession helper, just clear history on voice start."""
FILE = 'cli/nexus-cli.tsx'

with open(FILE, 'r', encoding='utf-8') as f:
    content = f.read()

# Step 1: Remove the ensureFreshVoiceSession helper function
old_helper = """const ensureFreshVoiceSession = async (
    sessionId: string,
    apiJson: (endpoint: string, init?: RequestInit) => Promise<any>,
    setSessionId: React.Dispatch<React.SetStateAction<string>>,
    setHistory: React.Dispatch<React.SetStateAction<Message[]>>
): Promise<string> => {
    // When on 'default' session, create a fresh session to avoid showing old history
    if (sessionId === 'default') {
        try {
            const created = await apiJson('/sessions/new', {method: 'POST'});
            if (created && created.id) {
                setSessionId(created.id);
                setHistory([]);
                return created.id;
            }
        } catch {
            // Fall back to current session if new session creation fails
        }
    }
    setHistory([]);
    return sessionId;
};

"""

if old_helper in content:
    content = content.replace(old_helper, "")
    print("STEP 1: Removed ensureFreshVoiceSession helper")
else:
    print("WARNING: Could not find helper to remove")

# Step 2: Replace the first call site with just setHistory([])
old_call1 = """                        // Create a fresh session for clean voice experience
                        const voiceSessionId = await ensureFreshVoiceSession(
                            sessionId, apiJson, setSessionId, setHistory
                        );

                        pushCommand(`\N{MICROPHONE} starting voice (${defaultMode})...`);
                        const startRes = await fetch(`${API_BASE}/voice/start`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ mode: defaultMode, session_id: voiceSessionId })
                        });"""

# Try to find and replace the first call site
lines = content.split('\n')
first_call_start = None
first_call_end = None
for i, line in enumerate(lines):
    if '// Create a fresh session for clean voice experience' in line:
        if first_call_start is None:
            first_call_start = i
        else:
            first_call_end = i

if first_call_start is not None:
    # Find the pushCommand and startRes lines after first call
    first_push = None
    for i in range(first_call_start, first_call_start + 10):
        if i < len(lines) and 'starting voice (${defaultMode})' in lines[i]:
            first_push = i
            break
    
    if first_push is not None:
        # Replace the 4-line call block with just setHistory([])
        indent = "                        "
        new_block = [f"{indent}setHistory([]);"]
        lines = lines[:first_call_start] + new_block + lines[first_push:]
        print("STEP 2: Replaced first call site with setHistory([])")
    else:
        print("WARNING: Could not find first pushCommand")
else:
    print("WARNING: Could not find first call site")

# Step 3: Replace the second call site similarly
# Re-find since lines changed
second_call_start = None
for i, line in enumerate(lines):
    if '// Create a fresh session for clean voice experience' in line:
        second_call_start = i
        break

if second_call_start is not None:
    second_push = None
    for i in range(second_call_start, second_call_start + 10):
        if i < len(lines) and 'starting voice (${sub})' in lines[i]:
            second_push = i
            break
    
    if second_push is not None:
        indent2 = "                    "
        new_block2 = [f"{indent2}setHistory([]);"]
        lines = lines[:second_call_start] + new_block2 + lines[second_push:]
        print("STEP 3: Replaced second call site with setHistory([])")
    else:
        print("WARNING: Could not find second pushCommand")
else:
    print("WARNING: Could not find second call site")

new_content = '\n'.join(lines)
with open(FILE, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Done!")
