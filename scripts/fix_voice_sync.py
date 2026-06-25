"""Patch cli/nexus-cli.tsx to fix old history reappearing after voice start."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('cli/nexus-cli.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')

# PATCH 1: Add voiceJustStartedRef after previousChatLineCount ref (line 1665)
old_ref = 'const previousChatLineCount = useRef(0);'
new_ref = 'const previousChatLineCount = useRef(0);\n    const voiceJustStartedRef = useRef(0);'
assert old_ref in content, "Could not find previousChatLineCount ref"
content = content.replace(old_ref, new_ref, 1)
print("Patch 1 applied: Added voiceJustStartedRef")

# PATCH 2: In the voice sync useEffect, add guard to skip history loading
# Find the history fetch block inside the voice sync effect
old_history_sync = """                // Sync chat history during voice
                if (sessionId) {
                    try {
                        const histResp = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);
                        if (histResp && histResp.messages && Array.isArray(histResp.messages)) {
                            setHistory(histResp.messages);
                        }
                    } catch {
                        // Ignore history load errors
                    }
                }"""

new_history_sync = """                // Sync chat history during voice (skip first 3s after voice starts)
                const skipUntil = voiceJustStartedRef.current;
                if (skipUntil && Date.now() < skipUntil) {
                    // Waiting for voice to settle — don't re-populate old history
                } else if (skipUntil) {
                    voiceJustStartedRef.current = 0;
                }
                if (sessionId && (!skipUntil || Date.now() >= skipUntil)) {
                    try {
                        const histResp = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);
                        if (histResp && histResp.messages && Array.isArray(histResp.messages)) {
                            setHistory(histResp.messages);
                        }
                    } catch {
                        // Ignore history load errors
                    }
                }"""

assert old_history_sync in content, "Could not find history sync block in voice useEffect"
content = content.replace(old_history_sync, new_history_sync, 1)
print("Patch 2 applied: Added skip guard to voice sync history loading")

# PATCH 3: Set voiceJustStartedRef when starting voice (default mode toggle)
old_voice_start_1 = """                        setHistory([]);
                        pushCommand(`🎙️ starting voice (${defaultMode})...`);"""

new_voice_start_1 = """                        setHistory([]);
                        voiceJustStartedRef.current = Date.now() + 3000;
                        pushCommand(`🎙️ starting voice (${defaultMode})...`);"""

assert old_voice_start_1 in content, "Could not find first voice start block"
content = content.replace(old_voice_start_1, new_voice_start_1, 1)
print("Patch 3 applied: Set guard in first voice start (default mode)")

# PATCH 4: Set voiceJustStartedRef when starting voice (explicit mode)
old_voice_start_2 = """                    setHistory([]);
                    pushCommand(`🎙️ starting voice (${sub})...`);"""

new_voice_start_2 = """                    setHistory([]);
                    voiceJustStartedRef.current = Date.now() + 3000;
                    pushCommand(`🎙️ starting voice (${sub})...`);"""

assert old_voice_start_2 in content, "Could not find second voice start block"
content = content.replace(old_voice_start_2, new_voice_start_2, 1)
print("Patch 4 applied: Set guard in second voice start (explicit mode)")

with open('cli/nexus-cli.tsx', 'w', encoding='utf-8') as f:
    f.write(content)

print("\nAll patches applied successfully!")
