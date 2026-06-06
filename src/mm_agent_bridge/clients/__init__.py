"""Agent client implementations.

Import the base class, factory, and all concrete clients from here::

    from mm_agent_bridge.clients import AgentClient, create_agent_client
    from mm_agent_bridge.clients import OpenCodeClient, CopilotClient
"""

from .base import AgentClient
from .factory import create_agent_client, register, supported_agent_types
from .copilot import CopilotClient  # noqa: F401 — triggers @register("copilot")
from .opencode import OpenCodeClient  # noqa: F401 — triggers @register("opencode")

__all__ = [
    "AgentClient",
    "CopilotClient",
    "OpenCodeClient",
    "create_agent_client",
    "register",
    "supported_agent_types",
]
