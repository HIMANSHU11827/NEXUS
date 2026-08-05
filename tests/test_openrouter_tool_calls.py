from providers.openrouter import OpenRouterProvider


def test_openrouter_native_tool_call_is_encoded_for_nexus_parser():
    text = OpenRouterProvider._tool_envelope([
        {
            "id": "call_1",
            "function": {
                "name": "bash",
                "arguments": '{"command":"Get-Location"}',
            },
        }
    ])

    assert text == '<function=bash>{"command": "Get-Location"}'


def test_openrouter_tool_payload_preserves_schemas_and_choice():
    payload = {"model": "test", "messages": []}
    OpenRouterProvider._add_tool_payload(
        payload,
        {"tools": [{"type": "function", "function": {"name": "bash"}}], "tool_choice": "auto"},
    )

    assert payload["tools"][0]["function"]["name"] == "bash"
    assert payload["tool_choice"] == "auto"
