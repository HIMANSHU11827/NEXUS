import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nexus_path  # noqa: F401

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from core.config_loader import NexusConfigLoader


def get_nexus_llm(temperature: float = 0.7, streaming: bool = True) -> ChatOpenAI:
    """
    Returns a LangChain-compatible LLM pointed at whatever provider
    is configured in nexus_config.yaml — no hardcoding required.
    """
    loader = NexusConfigLoader()
    config = loader.get_provider_config("local", "lm_studio")
    endpoint = config.get("endpoint", "http://localhost:1234/v1")
    model = config.get("default_model", "local-model")

    return ChatOpenAI(
        base_url=endpoint,
        api_key="lm-studio",         # LM Studio requires any non-empty key
        model=model,
        temperature=temperature,
        streaming=streaming,
    )


if __name__ == "__main__":
    llm = get_nexus_llm()
    msgs = [
        SystemMessage(content="You are NEXUS AI."),
        HumanMessage(content="Say hello in 5 words.")
    ]
    for chunk in llm.stream(msgs):
        print(chunk.content, end="", flush=True)
    print()
