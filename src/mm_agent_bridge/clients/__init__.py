"""Agent client implementations.

Import the base class and all concrete clients from here::

    from mm_agent_bridge.clients import AgentClient, OpenCodeClient, CopilotClient
"""

from .base import AgentClient
from .copilot import CopilotClient
from .opencode import OpenCodeClient

__all__ = ["AgentClient", "CopilotClient", "OpenCodeClient"]
