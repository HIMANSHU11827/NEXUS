from nexus.capabilities.intelligence.local_brain import NexusLocalBrain
from nexus.capabilities.intelligence.moa import MixtureOfArchitects


def test_moa_delegates_hybrid_request_instead_of_returning_empty_success():
    class Router:
        def generate(self, messages, **kwargs):
            return f"answered:{messages[-1]['content']}"

    result = MixtureOfArchitects(Router()).aggregate(
        messages=[{"role": "user", "content": "hello"}]
    )

    assert result == "answered:hello"


def test_moa_reports_missing_provider_mesh_explicitly():
    result = MixtureOfArchitects(object()).aggregate(messages=[])

    assert result.startswith("[MOA_ERROR]:")
    assert result != ""


def test_local_brain_uses_first_responding_local_provider():
    class Provider:
        def __init__(self, response):
            self.response = response

        def generate(self, **kwargs):
            return self.response

        def stream_generate(self, **kwargs):
            yield self.response

    class Factory:
        def __init__(self):
            self.providers = {
                "bad": Provider("Error: local server unavailable"),
                "good": Provider("local answer"),
            }

        def get_provider_by_name(self, group, name):
            return self.providers.get(name)

    brain = NexusLocalBrain(".")
    brain._factory = Factory()
    brain.DEFAULT_PROVIDERS = ("bad", "good")

    assert brain.generate(messages=[{"role": "user", "content": "hi"}]) == "local answer"
    assert list(brain.stream_generate(messages=[])) == ["local answer"]


def test_local_brain_never_reports_fake_image_success():
    result = NexusLocalBrain(".").scan_image("image.png")

    assert result.startswith("[LOCAL_BRAIN_ERROR]:")
    assert "no image inference was performed" in result
