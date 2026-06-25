"""Shell entry point for python -m shell"""
import asyncio
from shell import NexusShell
asyncio.run(NexusShell().start())
