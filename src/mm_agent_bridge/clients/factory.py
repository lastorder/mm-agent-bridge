"""Agent client factory with auto-registration.

Each concrete client module decorates its class with ``@register("name")``
which populates the internal registry.  The bot creates its client via
``create_agent_client(config)`` — no need to import specific client classes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import AgentClient

if TYPE_CHECKING:
    from mm_agent_bridge.config import Config

_REGISTRY: dict[str, type[AgentClient]] = {}


def register(agent_type: str):
    """Class decorator — registers a client class for the given *agent_type*."""

    def decorator(cls: type[AgentClient]) -> type[AgentClient]:
        _REGISTRY[agent_type] = cls
        return cls

    return decorator


def supported_agent_types() -> list[str]:
    """Return registered agent type names (sorted)."""
    return sorted(_REGISTRY)


def create_agent_client(config: Config) -> AgentClient:
    """Instantiate the correct agent client based on *config.agent_type*.

    Raises:
        ValueError: If *agent_type* is not registered.
    """
    cls = _REGISTRY.get(config.agent_type)
    if cls is None:
        available = ", ".join(supported_agent_types())
        raise ValueError(
            f"Unknown agent_type={config.agent_type!r}. Available: {available}"
        )
    return cls.from_config(config)
