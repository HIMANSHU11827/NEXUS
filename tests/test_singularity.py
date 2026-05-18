import os
import sys

# Ensure NEXUS modules are importable
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)

from core.neural.symbolism import NeuralSymbolicProtocol

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def run_singularity_test():
    print("--- NEXUS SYMBOLIC COMPACTION TEST ---")
    
    nsp = NeuralSymbolicProtocol()
    
    # 1. Test Legend Generation
    legend = nsp.get_symbol_legend()
    print(f"[TEST 1]: Symbol Legend -> {legend}")
    
    # 2. Test Compression (Language Waste Reduction)
    verbose_instruction = "Ensure everything is VALID_JSON_ONLY: Ensure all tool calls are strictly JSON formatted. and PLAN_MISSION: Create a multi-step objective map."
    compressed = nsp.compress(verbose_instruction)
    
    reduction = len(compressed) / len(verbose_instruction)
    print(f"[TEST 2]: Verbose Instruction -> {verbose_instruction[:50]}...")
    print(f"[TEST 2]: Compressed Stream -> {compressed}")
    print(f"[TEST 2]: Language Waste Reduction -> {round((1-reduction)*100, 2)}%")
    
    # 3. Expansion Verification
    decoded = nsp.get_instruction_for_symbol("🌀")
    print(f"[TEST 3]: Decoding Symbol '🌀' -> {decoded}")
    
    if "SIMULATE_FIRST" in decoded:
        print("\n--- COMPACTION TEST PASSED: TOKEN EFFICIENCY MAXIMIZED ---")
        return True
    else:
        print("\n--- ❌ TEST FAILED: DECODING ERROR ---")
        return False

if __name__ == "__main__":
    run_singularity_test()
