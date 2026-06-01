"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

_TRUTHY = ("true", "1", "yes")


def _get(name: str, default: str = "") -> str:
    """Read an optional env var, stripped of whitespace."""
    return os.environ.get(name, default).strip()


def _get_bool(name: str, default: str = "false") -> bool:
    """Read an optional boolean env var (true/1/yes → True)."""
    return _get(name, default).lower() in _TRUTHY


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

    # Agent backend selection: "opencode" or "copilot"
    agent_type: str = "opencode"

    # OpenCode (used when agent_type == "opencode")
    opencode_base_url: str = "http://localhost:36000"
    opencode_session_id: str = ""
    opencode_model_id: str = ""
    opencode_provider_id: str = ""

    # GitHub Copilot (used when agent_type == "copilot")
    copilot_session_id: str = ""
    copilot_model: str = "gpt-5.4"

    # Greeting / goodbye messages
    greeting_enabled: bool = False
    greeting_channel_id: str = ""
    greeting_message: str = "Agent is now online and ready."
    goodbye_message: str = "Agent is shutting down. Goodbye."

    # Bot messages (user-facing, shown in thread replies)
    msg_queued: str = "Your request has been queued. Please wait..."
    msg_processing: str = "Processing your request..."
    msg_error: str = "Sorry, an error occurred while processing your request."
    msg_empty: str = "Empty message after removing mention."
    msg_show_host: bool = False

    @classmethod
    def from_env(cls) -> Config:
        """Build a Config from the current environment variables.

        Raises:
            ValueError: If a required variable is missing or empty.
        """

        def _require(name: str) -> str:
            val = _get(name)
            if not val:
                raise ValueError(f"{name} environment variable is required")
            return val

        mm_url = _require("MM_URL")
        mm_token = _require("MM_TOKEN")

        agent_type = _get("AGENT_TYPE", "opencode").lower()
        if agent_type not in ("opencode", "copilot"):
            raise ValueError(
                f"AGENT_TYPE must be 'opencode' or 'copilot', got {agent_type!r}"
            )

        # --- OpenCode-specific ---
        opencode_model_id = ""
        opencode_provider_id = ""
        if agent_type == "opencode":
            opencode_model_id = _require("OPENCODE_MODEL_ID")
            opencode_provider_id = _require("OPENCODE_PROVIDER_ID")

        # --- Greeting / goodbye ---
        greeting_enabled = _get_bool("GREETING_ENABLED")
        greeting_channel_id = _get("GREETING_CHANNEL_ID")
        if greeting_enabled and not greeting_channel_id:
            raise ValueError(
                "GREETING_CHANNEL_ID is required when GREETING_ENABLED is true"
            )

        return cls(
            mm_url=mm_url,
            mm_token=mm_token,
            mm_port=int(_get("MM_PORT", "8065")),
            mm_scheme=_get("MM_SCHEME", "http"),
            bot_mention_name=_get("BOT_MENTION_NAME", "ai-agent"),
            agent_type=agent_type,
            opencode_base_url=_get("OPENCODE_BASE_URL", "http://localhost:36000"),
            opencode_session_id=_get("OPENCODE_SESSION_ID"),
            opencode_model_id=opencode_model_id,
            opencode_provider_id=opencode_provider_id,
            copilot_session_id=_get("COPILOT_SESSION_ID"),
            copilot_model=_get("COPILOT_MODEL", "gpt-5.4"),
            greeting_enabled=greeting_enabled,
            greeting_channel_id=greeting_channel_id,
            greeting_message=_get("GREETING_MESSAGE", "Agent is now online and ready."),
            goodbye_message=_get("GOODBYE_MESSAGE", "Agent is shutting down. Goodbye."),
            msg_queued=_get("MSG_QUEUED", "Your request has been queued. Please wait..."),
            msg_processing=_get("MSG_PROCESSING", "Processing your request..."),
            msg_error=_get("MSG_ERROR", "Sorry, an error occurred while processing your request."),
            msg_empty=_get("MSG_EMPTY", "Empty message after removing mention."),
            msg_show_host=_get_bool("MSG_SHOW_HOST"),
        )
