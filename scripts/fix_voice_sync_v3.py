"""Patch cli/nexus-cli.tsx to fix old history reappearing after voice start."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('cli/nexus-cli.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# PATCH 1: Add voiceJustStartedRef after previousChatLineCount ref
old1 = 'const previousChatLineCount = useRef(0);'
new1 = 'const previousChatLineCount = useRef(0);\n    const voiceJustStartedRef = useRef(0);'
assert old1 in content, "PATCH 1 FAILED"
content = content.replace(old1, new1, 1)
print("Patch 1 OK: Added voiceJustStartedRef")

# PATCH 2: Add guard to syncHistory - wrap voice status + history in skip check
# Find the exact beginning of syncHistory
old2 = "        const syncHistory = async () => {\n            try {\n                const voiceData = await apiJson('/voice/status').catch(() => null);"
assert old2 in content, "PATCH 2 FAILED: syncHistory start not found"
new2 = "        const syncHistory = async () => {\n            try {\n                // Skip history loading for 3s after voice starts\n                const skipUntil = voiceJustStartedRef.current;\n                if (skipUntil && Date.now() < skipUntil) {\n                    return; // Grace period - don't re-populate old history\n                }\n                if (skipUntil) voiceJustStartedRef.current = 0;\n                const voiceData = await apiJson('/voice/status').catch(() => null);"
content = content.replace(old2, new2, 1)
print("Patch 2 OK: Added skip guard to syncHistory")

# PATCH 3: Set voiceJustStartedRef when starting voice (default mode toggle)
old3 = "                        setHistory([]);\n                        pushCommand("
# We need to find the exact match - let's search for the specific context
idx3 = content.find("                        setHistory([]);\n                        pushCommand(")
assert idx3 > 0, "PATCH 3 FAILED"
# Find the exact string including the emoji
end3 = content.find("\n", idx3 + 100)
if end3 < 0:
    end3 = idx3 + 200
line3 = content[idx3:end3]
# Insert voiceJustStartedRef before pushCommand
content = content[:idx3] + "                        setHistory([]);\n                        voiceJustStartedRef.current = Date.now() + 3000;\n" + content[idx3 + len("                        setHistory([]);\n"):]
print("Patch 3 OK: Set guard in first voice start")

# PATCH 4: Set voiceJustStartedRef when starting voice (explicit mode)
old4 = "                    setHistory([]);\n                    pushCommand("
idx4 = content.find("                    setHistory([]);\n                    pushCommand(")
assert idx4 > 0, "PATCH 4 FAILED"
content = content[:idx4] + "                    setHistory([]);\n                    voiceJustStartedRef.current = Date.now() + 3000;\n" + content[idx4 + len("                    setHistory([]);\n"):]
print("Patch 4 OK: Set guard in second voice start")

with open('cli/nexus-cli.tsx', 'w', encoding='utf-8') as f:
    f.write(content)

print("\nAll 4 patches applied successfully!")
