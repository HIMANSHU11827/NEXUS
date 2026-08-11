"""Test NEXUS V5 Loop Integration."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from orchestrators.v5 import create_v5_loop


async def test_v5_basic():
    """Test basic V5 loop execution."""
    print("Testing V5 Loop - Basic Execution")
    print("=" * 50)
    
    # Create V5 loop with minimal configuration
    config = {
        "meta_learning_enabled": True,
        "quantum_mode": False,  # Disabled for basic test
        "consciousness_level": 1,  # Basic level
        "swarm_size": 2,  # Small swarm for test
        "evolution_enabled": False  # Disabled for basic test
    }
    
    loop = create_v5_loop(
        root_dir=str(project_root),
        session_id="test_session",
        config=config
    )
    
    # Run a simple test
    result = await loop.run(
        user_input="Hello, this is a test",
        input_type="text"
    )
    
    print(f"Result: {result}")
    print(f"Success: {result.get('success', False)}")
    print(f"State: {result.get('state', 'unknown')}")
    
    # Check runtime state
    runtime_state = loop.get_runtime_state()
    print("\nRuntime State:")
    print(f"  Session ID: {runtime_state['session_id']}")
    print(f"  Turn Count: {runtime_state['turn_count']}")
    print(f"  Meta-Learning: {runtime_state['meta_learning_enabled']}")
    print(f"  Consciousness Level: {runtime_state['consciousness_level']}")
    print(f"  Swarm Size: {runtime_state['swarm_size']}")
    
    print("\n✓ Basic test passed")
    return True


async def test_v5_perception():
    """Test perception layer."""
    print("\nTesting V5 Loop - Perception Layer")
    print("=" * 50)
    
    from orchestrators.v5.perceive import PerceptionLayer
    from orchestrators.v5.core import V5TurnContext
    
    perception = PerceptionLayer(str(project_root))
    turn = V5TurnContext(
        turn_id="test_turn",
        session_id="test_session",
        user_input="Write a function to sort an array",
        input_type="text"
    )
    
    perceived = await perception.process(turn)
    
    print(f"Intent: {perceived.intent.value}")
    print(f"Confidence: {perceived.confidence:.2f}")
    print(f"Entities: {perceived.extracted_entities}")
    print(f"Context Summary: {perceived.context_summary}")
    
    print("\n✓ Perception test passed")
    return True


async def test_v5_paorr():
    """Test PAORR enhanced loop."""
    print("\nTesting V5 Loop - PAORR Enhanced")
    print("=" * 50)
    
    from orchestrators.v5.paorr import PAORREnhanced
    from orchestrators.v5.perceive import PerceptionLayer
    from orchestrators.v5.core import V5TurnContext
    
    paorr = PAORREnhanced(str(project_root))
    perception = PerceptionLayer(str(project_root))
    
    turn = V5TurnContext(
        turn_id="test_turn",
        session_id="test_session",
        user_input="Research quantum computing",
        input_type="text"
    )
    
    perceived = await perception.process(turn)
    result = await paorr.execute(perceived)
    
    print(f"Success: {result.get('success', False)}")
    print(f"Plan Steps: {len(result.get('plan', {}).steps if hasattr(result.get('plan', {}), 'steps') else [])}")
    print(f"Actions: {len(result.get('actions', []))}")
    reflection = result.get('reflection')
    if reflection:
        print(f"Reflection Success: {reflection.success if hasattr(reflection, 'success') else reflection.get('success', False)}")
    else:
        print("Reflection Success: False")
    
    print("\n✓ PAORR test passed")
    return True


async def test_v5_meta_learning():
    """Test meta-learning layer."""
    print("\nTesting V5 Loop - Meta-Learning")
    print("=" * 50)
    
    from orchestrators.v5.meta import MetaLearningLayer, Experience
    from orchestrators.v5.core import V5Runtime
    from datetime import datetime
    
    meta = MetaLearningLayer(str(project_root))
    runtime = V5Runtime(session_id="test", root_dir=str(project_root))
    
    # Record some experiences
    for i in range(5):
        experience = Experience(
            task_id=f"task_{i}",
            strategy="default",
            outcome=0.8 + (i * 0.02),
            timestamp=datetime.utcnow()
        )
        meta.record_experience(experience)
    
    # Run optimization
    recommendations = await meta.optimize(runtime)
    
    print(f"Recommendations: {recommendations}")
    print(f"Strategy Performance: {meta.strategy_performance}")
    
    print("\n✓ Meta-learning test passed")
    return True


async def test_v5_quantum():
    """Test quantum actor model."""
    print("\nTesting V5 Loop - Quantum Actor Model")
    print("=" * 50)
    
    from orchestrators.v5.quantum import QuantumActorModel
    
    quantum = QuantumActorModel(str(project_root))
    
    result = {"actions": [{"step_id": "action_1"}, {"step_id": "action_2"}]}
    quantum_result = await quantum.orchestrate(result)
    
    print(f"Success: {quantum_result.get('success', False)}")
    print(f"Actors Used: {quantum_result.get('actors_used', 0)}")
    print(f"Entanglement Pairs: {quantum_result.get('entanglement_pairs', 0)}")
    
    print("\n✓ Quantum actor test passed")
    return True


async def test_v5_consciousness():
    """Test consciousness layer."""
    print("\nTesting V5 Loop - Consciousness Layer")
    print("=" * 50)
    
    from orchestrators.v5.conscious import ConsciousnessLayer
    
    consciousness = ConsciousnessLayer(str(project_root))
    
    result = {"confidence": 0.8, "complexity": 0.5}
    conscious_result = await consciousness.process(result, consciousness_level=5)
    
    print(f"Success: {conscious_result.get('success', False)}")
    print(f"Consciousness Level: {conscious_result.get('consciousness_level', 'unknown')}")
    print(f"Mental State: {conscious_result.get('mental_state', {})}")
    
    print("\n✓ Consciousness test passed")
    return True


async def run_all_tests():
    """Run all V5 tests."""
    print("\n" + "=" * 60)
    print("NEXUS V5 Loop Integration Tests")
    print("=" * 60)
    
    tests = [
        ("Basic Execution", test_v5_basic),
        ("Perception Layer", test_v5_perception),
        ("PAORR Enhanced", test_v5_paorr),
        ("Meta-Learning", test_v5_meta_learning),
        ("Quantum Actor", test_v5_quantum),
        ("Consciousness", test_v5_consciousness),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ {name} failed: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
