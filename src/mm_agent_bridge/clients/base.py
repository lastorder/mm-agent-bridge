"""Abstract base class for AI agent clients.

All agent backends (OpenCode, Copilot, etc.) implement this interface
so the bot can swap backends without changing any other code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class AgentClient(ABC):
    """Async client interface for an AI coding agent."""

    @abstractmethod
    async def chat(self, text: str) -> str:
        """Send *text* to the agent and return the assistant's reply.

        Raises on network/API errors — callers are expected to handle
        exceptions.
        """
