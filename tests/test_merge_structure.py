import importlib


def test_cognition_package_exposes_core_components():
    reasoning = importlib.import_module("nexus.capabilities.reasoning.hyper_engine")
    moe = importlib.import_module("nexus.capabilities.intelligence.moe_router")
    local_brain = importlib.import_module("nexus.capabilities.intelligence.local_brain")
    assert hasattr(reasoning, "HyperReasoningEngine")
    assert hasattr(moe, "NexusMoERouter")
    assert hasattr(local_brain, "NexusLocalBrain")


def test_kernel_telemetry_module_is_available():
    telemetry = importlib.import_module("nexus.runtime.kernel.telemetry")
    assert hasattr(telemetry, "NexusTelemetryDB")
