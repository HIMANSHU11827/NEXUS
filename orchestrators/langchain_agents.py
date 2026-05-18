import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nexus_path  # noqa: F401 — ensures project root on sys.path for IDE + runtime

from langchain.agents import create_react_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.memory import ConversationBufferMemory
from langchain_core.messages import SystemMessage
from langchain_core.prompts import PromptTemplate

from core.providers.langchain_provider import get_nexus_llm
from core.providers.langchain_tools import NEXUS_TOOLS


# ─────────────────────────────────────────────
# PERSISTENT CONVERSATION MEMORY
# ─────────────────────────────────────────────
def get_memory() -> ConversationBufferMemory:
    """Returns a session-wide memory object for the agent to use."""
    return ConversationBufferMemory(
        memory_key="chat_history",
        return_messages=True
    )


# ─────────────────────────────────────────────
# REACT AGENT (TOOL-CALLING AGENT)
# ─────────────────────────────────────────────
REACT_SYSTEM = """You are NEXUS AI, an autonomous operating system agent.
You have access to the following tools: {tools}

Use the following format:
Thought: think about what to do
Action: the tool to use (one of [{tool_names}])
Action Input: the input to the tool
Observation: the result of the tool
... (repeat Thought/Action/Observation as needed)
Thought: I now have the final answer
Final Answer: the answer to the user's question

Begin!
Question: {input}
{agent_scratchpad}"""


def create_nexus_agent(memory: ConversationBufferMemory = None) -> AgentExecutor:
    """Creates a fully functional NEXUS ReAct agent with tool access and memory."""
    llm = get_nexus_llm(streaming=False)  # ReAct needs non-streaming for tool parsing

    prompt = PromptTemplate.from_template(REACT_SYSTEM)
    agent = create_react_agent(llm, NEXUS_TOOLS, prompt)

    return AgentExecutor(
        agent=agent,
        tools=NEXUS_TOOLS,
        memory=memory,
        verbose=False,
        handle_parsing_errors=True,
        max_iterations=5,
    )


# ─────────────────────────────────────────────
# SIMPLE CHAT CHAIN (no tools, fast for chat)
# ─────────────────────────────────────────────
def create_chat_chain():
    """Simple streaming chat chain with memory — no tools, just fast conversation."""
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    llm = get_nexus_llm(streaming=True)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are NEXUS AI, a helpful and concise assistant. Answer directly."),
        ("human", "{input}"),
    ])
    return prompt | llm | StrOutputParser()


if __name__ == "__main__":
    print("=== NEXUS LANGCHAIN CHAT TEST ===")
    chain = create_chat_chain()
    for chunk in chain.stream({"input": "What is LangChain in 10 words?"}):
        print(chunk, end="", flush=True)
    print()
