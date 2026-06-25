"""Fix the broken brace structure in syncHistory function."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('cli/nexus-cli.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# The current broken structure:
#     if (!inGracePeriod) {
#     const loaded = ...
#     if (Array.isArray(loaded)) {
#         ...
#         setHistory(prev => {
#             ...
#         });
#     }
# } catch {
#     // Ignore history load errors
# }
# }

# We need to find the exact broken block and fix it
# The issue is the closing of the if block and catch block are mismatched

# Find the exact pattern with the if guard
old_block = """                // Only fetch history after grace period (prevents old history flash on voice start)
                if (!inGracePeriod) {
                const loaded = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);"""

new_block = """                // Only fetch history after grace period (prevents old history flash on voice start)
                if (!inGracePeriod) {
                    const loaded = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);"""

if old_block in content:
    content = content.replace(old_block, new_block, 1)
    print("Fixed indentation of history fetch")
else:
    print("Could not find the exact pattern for history fetch indentation")

# Now fix the closing of the if block - it needs to close before the catch
# Find the closing pattern
old_closing = """                }
            } catch {
                // Ignore history load errors
            }
            }"""

new_closing = """                }
                }
            } catch {
                // Ignore history load errors
            }"""

if old_closing in content:
    content = content.replace(old_closing, new_closing, 1)
    print("Fixed closing braces")
else:
    # Try alternative pattern
    old_closing2 = """            }
        } catch {
                // Ignore history load errors
            }
            }"""
    new_closing2 = """            }
                }
            } catch {
                // Ignore history load errors
            }"""
    if old_closing2 in content:
        content = content.replace(old_closing2, new_closing2, 1)
        print("Fixed closing braces (alt pattern)")
    else:
        print("Could not find closing pattern - let me check what's there")
        # Find the catch block
        idx = content.find("// Ignore history load errors")
        if idx > 0:
            # Show context around it
            start = max(0, idx - 300)
            end = min(len(content), idx + 200)
            print("CONTEXT:")
            print(repr(content[start:end]))

with open('cli/nexus-cli.tsx', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done!")
