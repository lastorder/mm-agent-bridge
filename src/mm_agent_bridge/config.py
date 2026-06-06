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
    mention_by_id: bool = False

    # Agent backend selection: "opencode" or "copilot"
    agent_type: str = "opencode"

    # OpenCode (used when agent_type == "opencode")
    opencode_base_url: str = ""
    opencode_session_id: str = ""
    opencode_model_id: str = ""
    opencode_provider_id: str = ""
    opencode_variant: str = ""
    opencode_password: str = ""
    opencode_username: str = "opencode"

    # GitHub Copilot (used when agent_type == "copilot")
    copilot_session_id: str = ""
    copilot_model: str = "gpt-5.4"

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

        # --- OpenCode-specific (required when agent_type == "opencode") ---
        opencode_base_url = ""
        opencode_model_id = ""
        opencode_provider_id = ""
        if agent_type == "opencode":
            opencode_base_url = _require("OPENCODE_BASE_URL")
            opencode_model_id = _require("OPENCODE_MODEL_ID")
            opencode_provider_id = _require("OPENCODE_PROVIDER_ID")

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
            opencode_base_url=opencode_base_url,
            opencode_session_id=_get("OPENCODE_SESSION_ID"),
            opencode_model_id=opencode_model_id,
            opencode_provider_id=opencode_provider_id,
            opencode_variant=_get("OPENCODE_VARIANT"),
            opencode_password=_get("OPENCODE_SERVER_PASSWORD"),
            opencode_username=_get("OPENCODE_SERVER_USERNAME", "opencode"),
            copilot_session_id=_get("COPILOT_SESSION_ID"),
            copilot_model=_get("COPILOT_MODEL", "gpt-5.4"),
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
