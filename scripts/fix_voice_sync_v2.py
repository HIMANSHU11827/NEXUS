"""Patch cli/nexus-cli.tsx to fix old history reappearing after voice start."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('cli/nexus-cli.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# PATCH 1: Add voiceJustStartedRef after previousChatLineCount ref
old1 = 'const previousChatLineCount = useRef(0);'
new1 = 'const previousChatLineCount = useRef(0);\n    const voiceJustStartedRef = useRef(0);'
assert old1 in content, f"PATCH 1 FAILED: Could not find '{old1}'"
content = content.replace(old1, new1, 1)
print("Patch 1 OK: Added voiceJustStartedRef")

# PATCH 2: Add guard to syncHistory inside the voice useEffect
# The exact block from the file:
old2 = """        const syncHistory = async () => {
            try {
                const voiceData = await apiJson('/voice/status').catch(() => null);"""

new2 = """        const syncHistory = async () => {
            try {
                // Skip history loading for 3s after voice starts (prevent old history flash)
                const skipUntil = voiceJustStartedRef.current;
                if (skipUntil && Date.now() < skipUntil) {
                    // Still in voice startup grace period — only sync voice status
                } else {
                    if (skipUntil) voiceJustStartedRef.current = 0;
                const voiceData = await apiJson('/voice/status').catch(() => null);"""

assert old2 in content, f"PATCH 2 FAILED: Could not find syncHistory block"
content = content.replace(old2, new2, 1)
print("Patch 2 OK: Added skip guard to syncHistory")

# PATCH 3: Add closing brace for the else block before the history fetch
# Find the line with history fetch that follows the voice status block
old3 = """                }

                const loaded = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);"""

new3 = """                }

                // Only fetch history if not in grace period
                if (!voiceJustStartedRef.current || Date.now() >= voiceJustStartedRef.current) {
                const loaded = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);"""

# There may be multiple occurrences of this pattern - find the one inside syncHistory
# Let's search more specifically
old3_exact = """                } else if (voiceData && !voiceData.running) {
                    setVoiceMode('off');
                    setVoicePhase('off');
                    setVoiceTranscriptPreview('');
                    setVoiceReplyPreview('');
                    return;
                }

                const loaded = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);"""

new3_exact = """                } else if (voiceData && !voiceData.running) {
                    setVoiceMode('off');
                    setVoicePhase('off');
                    setVoiceTranscriptPreview('');
                    setVoiceReplyPreview('');
                    return;
                }
                }

                // Only fetch history if not in grace period
                if (!voiceJustStartedRef.current || Date.now() >= voiceJustStartedRef.current) {
                const loaded = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);"""

assert old3_exact in content, f"PATCH 3 FAILED: Could not find history fetch block"
content = content.replace(old3_exact, new3_exact, 1)
print("Patch 3 OK: Added history fetch guard")

# PATCH 4: Close the if block before the catch
old4 = """            } catch {
                // Ignore history load errors
            }
        };"""

new4 = """            } catch {
                // Ignore history load errors
            }
            }
        };"""

# Only replace the one inside syncHistory (first occurrence)
assert old4 in content, f"PATCH 4 FAILED: Could not find catch block"
content = content.replace(old4, new4, 1)
print("Patch 4 OK: Closed history fetch guard block")

# PATCH 5: Set voiceJustStartedRef when starting voice (default mode toggle)
old5 = """                        setHistory([]);
                        pushCommand(`\u{1f399}\u{fe0f} starting voice (${defaultMode})...`);"""

new5 = """                        setHistory([]);
                        voiceJustStartedRef.current = Date.now() + 3000;
                        pushCommand(`\u{1f399}\u{fe0f} starting voice (${defaultMode})...`);"""

assert old5 in content, f"PATCH 5 FAILED: Could not find first voice start"
content = content.replace(old5, new5, 1)
print("Patch 5 OK: Set guard in first voice start")

# PATCH 6: Set voiceJustStartedRef when starting voice (explicit mode)
old6 = """                    setHistory([]);
                    pushCommand(`\u{1f399}\u{fe0f} starting voice (${sub})...`);"""

new6 = """                    setHistory([]);
                    voiceJustStartedRef.current = Date.now() + 3000;
                    pushCommand(`\u{1f399}\u{fe0f} starting voice (${sub})...`);"""

assert old6 in content, f"PATCH 6 FAILED: Could not find second voice start"
content = content.replace(old6, new6, 1)
print("Patch 6 OK: Set guard in second voice start")

with open('cli/nexus-cli.tsx', 'w', encoding='utf-8') as f:
    f.write(content)

print("\nAll 6 patches applied successfully!")
