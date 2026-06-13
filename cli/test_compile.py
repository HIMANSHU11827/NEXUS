#!/usr/bin/env python3
"""Compile check TSX without npm."""
import subprocess, sys, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Check npx tsc --noEmit
print("Running npx tsc --noEmit...")
result = subprocess.run(["npx", "tsc", "--noEmit"], capture_output=True, text=True)
if result.returncode == 0:
    print("✅ TypeScript compiles clean — 0 errors")
else:
    print(f"❌ TypeScript errors:\n{result.stdout}\n{result.stderr}")
    sys.exit(1)

# Check python server/shell
os.chdir("..")
for f in ["server/__init__.py", "shell/__init__.py", "nexus/__init__.py"]:
    print(f"Checking {f}...")
    result = subprocess.run([sys.executable, "-m", "py_compile", f], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  ✅ {f}")
    else:
        print(f"  ❌ {f}: {result.stderr}")
        sys.exit(1)

print("\n🎉 ALL FILES COMPILE CLEAN")
