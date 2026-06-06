"""Abstract base class for AI agent clients.

All agent backends (OpenCode, Copilot, etc.) implement this interface
so the bot can swap backends without changing any other code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mm_agent_bridge.config import Config


class AgentClient(ABC):
    """Async client interface for an AI coding agent."""

    @classmethod
    @abstractmethod
    def from_config(cls, config: Config) -> "AgentClient":
        """Create an instance from the application :class:`Config`.

        Each concrete client extracts its backend-specific sub-config
        (e.g. ``config.opencode``, ``config.copilot``) and constructs
        itself from those fields.
        """

    @abstractmethod
    async def chat(self, text: str) -> str:
        """Send *text* to the agent and return the assistant's reply.

        Raises on network/API errors — callers are expected to handle
        exceptions.
        """
