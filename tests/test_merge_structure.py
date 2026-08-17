import importlib


def test_cognition_package_exposes_core_components():
    cognition = importlib.import_module("cognition")
    assert hasattr(cognition, "HyperReasoningEngine")
    assert hasattr(cognition, "NexusMoERouter")
    assert hasattr(cognition, "NexusLocalBrain")


def test_kernel_telemetry_module_is_available():
    telemetry = importlib.import_module("nexus.runtime.kernel.telemetry")
    assert hasattr(telemetry, "NexusTelemetryDB")
