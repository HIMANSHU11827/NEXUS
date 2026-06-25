import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils.nexus_path as nexus_path  # noqa: F401

from langchain_core.tools import tool
from tool_adapters import RegistryTerminalTool as TerminalTool
from tool_adapters import RegistryFileTools as NexusFileTools
from rag.engine import NexusAtlasRAG

_terminal = TerminalTool("./workspace")
_files = NexusFileTools("./workspace")
_rag = NexusAtlasRAG("./knowledge")


@tool
def run_shell(command: str) -> str:
    """Execute a shell command on the host system and return its output."""
    return _terminal.execute(command)


@tool
def write_file(filename_and_content: str) -> str:
    """
    Write content to a file in the workspace.
    Input format: 'filename.ext|||file content here'
    """
    try:
        name, content = filename_and_content.split("|||", 1)
        return _files.write_file(name.strip(), content.strip())
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def read_file(filename: str) -> str:
    """Read and return the content of a file from the workspace."""
    return _files.read_file(filename.strip())


@tool
def knowledge_search(query: str) -> str:
    """Search the NEXUS knowledge vault for relevant stored information."""
    return _rag.retrieve_as_text(query)


@tool
def knowledge_store(key_and_content: str) -> str:
    """
    Store a fact into the NEXUS knowledge vault.
    Input format: 'key|||content'
    """
    try:
        key, content = key_and_content.split("|||", 1)
        _rag.store_document(key.strip(), content.strip())
        return f"Stored '{key.strip()}' in knowledge vault."
    except Exception as e:
        return f"Error: {str(e)}"


# Export as a list for easy import
NEXUS_TOOLS = [run_shell, write_file, read_file, knowledge_search, knowledge_store]
