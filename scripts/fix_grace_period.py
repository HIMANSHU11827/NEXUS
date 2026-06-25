"""Wrap the history fetch in syncHistory with inGracePeriod guard."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('cli/nexus-cli.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# The history fetch block starts after the voice status block
# We need to find the exact text and wrap it with `if (!inGracePeriod) {`
old = """                }

                const loaded = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);"""

new = """                }

                // Only fetch history after grace period (prevents old history flash on voice start)
                if (!inGracePeriod) {
                const loaded = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);"""

count = content.count(old)
print(f"Found {count} occurrences of old block")

if count == 1:
    content = content.replace(old, new, 1)
    print("Wrapped history fetch with inGracePeriod guard")
else:
    print(f"ERROR: Expected 1 occurrence, found {count}")
    sys.exit(1)

# Now find the closing of the history fetch try block and add the closing brace
old_close = """            } catch {
                // Ignore history load errors
            }
        };"""

new_close = """            } catch {
                // Ignore history load errors
            }
            }
        };"""

count2 = content.count(old_close)
print(f"Found {count2} occurrences of catch block")

if count2 == 1:
    content = content.replace(old_close, new_close, 1)
    print("Closed inGracePeriod guard block")
else:
    print(f"ERROR: Expected 1 occurrence, found {count2}")
    sys.exit(1)

with open('cli/nexus-cli.tsx', 'w', encoding='utf-8') as f:
    f.write(content)

print("\nDone! History fetch now skips during grace period.")
