"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

_TRUTHY = ("true", "1", "yes")

# Backends that Config.from_env() knows how to load.
# Update this when adding a new backend.
_SUPPORTED_BACKENDS = ("opencode", "copilot")


def _get(name: str, default: str = "") -> str:
    """Read an optional env var, stripped of whitespace."""
    return os.environ.get(name, default).strip()


def _get_bool(name: str, default: str = "false") -> bool:
    """Read an optional boolean env var (true/1/yes -> True)."""
    return _get(name, default).lower() in _TRUTHY


def _require(name: str) -> str:
    """Read a required env var; raise ValueError if missing/empty."""
    val = _get(name)
    if not val:
        raise ValueError(f"{name} environment variable is required")
    return val


# ---------------------------------------------------------------------------
# Backend-specific config dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenCodeConfig:
    """OpenCode backend settings.

    Field names match :class:`~mm_agent_bridge.clients.opencode.OpenCodeClient`
    constructor parameters so ``OpenCodeClient(**asdict(oc))`` works.
    """

    base_url: str
    model_id: str
    provider_id: str
    session_id: str = ""
    variant: str = ""
    password: str = ""
    username: str = "opencode"

    @classmethod
    def from_env(cls) -> OpenCodeConfig:
        """Read and validate OpenCode-specific env vars."""
        return cls(
            base_url=_require("OPENCODE_BASE_URL"),
            model_id=_require("OPENCODE_MODEL_ID"),
            provider_id=_require("OPENCODE_PROVIDER_ID"),
            session_id=_get("OPENCODE_SESSION_ID"),
            variant=_get("OPENCODE_VARIANT"),
            password=_get("OPENCODE_SERVER_PASSWORD"),
            username=_get("OPENCODE_SERVER_USERNAME", "opencode"),
        )


@dataclass(frozen=True)
class CopilotConfig:
    """GitHub Copilot backend settings.

    Field names match :class:`~mm_agent_bridge.clients.copilot.CopilotClient`
    constructor parameters so ``CopilotClient(**asdict(cc))`` works.
    """

    session_id: str = ""
    model: str = "gpt-5.4"

    @classmethod
    def from_env(cls) -> CopilotConfig:
        """Read Copilot-specific env vars."""
        return cls(
            session_id=_get("COPILOT_SESSION_ID"),
            model=_get("COPILOT_MODEL", "gpt-5.4"),
        )


# ---------------------------------------------------------------------------
# Main application config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """Application configuration.

    All values are read from environment variables.
    See .env.example for the full list.
    """

    # Mattermost
    mm_url: str
    mm_token: str
    mm_port: int = 8065
    mm_scheme: str = "http"

    # Bot
    bot_mention_name: str = "ai-agent"
    mention_by_id: bool = False

    # Agent backend selection
    agent_type: str = "opencode"
    opencode: OpenCodeConfig | None = None
    copilot: CopilotConfig | None = None

    # Greeting / goodbye messages
    greeting_enabled: bool = False
    greeting_channel_id: str = ""
    greeting_message: str = "Agent is now online and ready. You can use @ai-agent to request my support."
    goodbye_message: str = "Agent is shutting down. Goodbye."

    # Queue
    queue_max_size: int = 10

    # Thread context
    thread_context_max_messages: int = 20

    # Bot messages (user-facing, shown in thread replies)
    msg_queued: str = "Your request has been queued. Please wait..."
    msg_queue_full: str = "Agent is busy, please try again later."
    msg_processing: str = "Processing your request..."
    msg_error: str = "Sorry, an error occurred while processing your request."
    msg_empty: str = "Empty message after removing mention."
    msg_show_host: bool = True

    @classmethod
    def from_env(cls) -> Config:
        """Build a Config from the current environment variables.

        Raises:
            ValueError: If a required variable is missing or empty.
        """
        mm_url = _require("MM_URL")
        mm_token = _require("MM_TOKEN")

        agent_type = _get("AGENT_TYPE", "opencode").lower()
        if agent_type not in _SUPPORTED_BACKENDS:
            raise ValueError(
                f"AGENT_TYPE must be one of {_SUPPORTED_BACKENDS}, got {agent_type!r}"
            )

        # --- Backend-specific config ---
        opencode = OpenCodeConfig.from_env() if agent_type == "opencode" else None
        copilot = CopilotConfig.from_env() if agent_type == "copilot" else None

        # --- Greeting / goodbye ---
        greeting_enabled = _get_bool("GREETING_ENABLED")
        greeting_channel_id = _get("GREETING_CHANNEL_ID")
        if greeting_enabled and not greeting_channel_id:
            raise ValueError(
                "GREETING_CHANNEL_ID is required when GREETING_ENABLED is true"
            )

        bot_mention_name = _get("BOT_MENTION_NAME", "ai-agent")
        default_greeting = (
            f"Agent is now online and ready."
            f" You can use @{bot_mention_name} to request my support."
        )

        return cls(
            mm_url=mm_url,
            mm_token=mm_token,
            mm_port=int(_get("MM_PORT", "8065")),
            mm_scheme=_get("MM_SCHEME", "http"),
            bot_mention_name=bot_mention_name,
            mention_by_id=_get_bool("MENTION_BY_ID"),
            agent_type=agent_type,
            opencode=opencode,
            copilot=copilot,
            greeting_enabled=greeting_enabled,
            greeting_channel_id=greeting_channel_id,
            greeting_message=_get("GREETING_MESSAGE", default_greeting),
            goodbye_message=_get("GOODBYE_MESSAGE", "Agent is shutting down. Goodbye."),
            thread_context_max_messages=int(_get("THREAD_CONTEXT_MAX_MESSAGES", "20")),
            queue_max_size=int(_get("QUEUE_MAX_SIZE", "10")),
            msg_queued=_get("MSG_QUEUED", "Your request has been queued. Please wait..."),
            msg_queue_full=_get("MSG_QUEUE_FULL", "Agent is busy, please try again later."),
            msg_processing=_get("MSG_PROCESSING", "Processing your request..."),
            msg_error=_get("MSG_ERROR", "Sorry, an error occurred while processing your request."),
            msg_empty=_get("MSG_EMPTY", "Empty message after removing mention."),
            msg_show_host=_get_bool("MSG_SHOW_HOST", "true"),
        )
