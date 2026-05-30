"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


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
    opencode_session_id: str = ""  # optional; creates new session if empty/invalid
    opencode_model_id: str = ""
    opencode_provider_id: str = ""

    # GitHub Copilot (used when agent_type == "copilot")
    # No token needed — SDK uses local Copilot CLI credentials.
    copilot_session_id: str = ""  # optional; creates new session if empty/invalid
    copilot_model: str = "gpt-5.4"

    # Greeting / goodbye messages
    greeting_enabled: bool = False
    greeting_channel_id: str = ""
    greeting_message: str = "Agent is now online and ready."
    goodbye_message: str = "Agent is shutting down. Goodbye."

    @classmethod
    def from_env(cls) -> Config:
        """Build a Config from the current environment variables.

        Raises:
            ValueError: If a required variable is missing or empty.
        """

        def _require(name: str) -> str:
            val = os.environ.get(name, "").strip()
            if not val:
                raise ValueError(f"{name} environment variable is required")
            return val

        mm_url = _require("MM_URL")
        mm_token = _require("MM_TOKEN")

        agent_type = os.environ.get("AGENT_TYPE", "opencode").strip().lower()
        if agent_type not in ("opencode", "copilot"):
            raise ValueError(
                f"AGENT_TYPE must be 'opencode' or 'copilot', got {agent_type!r}"
            )

        # --- OpenCode-specific ---
        opencode_session_id = os.environ.get("OPENCODE_SESSION_ID", "").strip()
        opencode_model_id = ""
        opencode_provider_id = ""
        opencode_base_url = os.environ.get(
            "OPENCODE_BASE_URL", "http://localhost:36000"
        ).strip()

        if agent_type == "opencode":
            opencode_model_id = _require("OPENCODE_MODEL_ID")
            opencode_provider_id = _require("OPENCODE_PROVIDER_ID")

        # --- Copilot-specific ---
        copilot_session_id = os.environ.get("COPILOT_SESSION_ID", "").strip()
        copilot_model = os.environ.get("COPILOT_MODEL", "gpt-5.4").strip()

        # --- Greeting / goodbye ---
        greeting_enabled = os.environ.get("GREETING_ENABLED", "false").strip().lower() in (
            "true",
            "1",
            "yes",
        )
        greeting_channel_id = os.environ.get("GREETING_CHANNEL_ID", "").strip()
        if greeting_enabled and not greeting_channel_id:
            raise ValueError(
                "GREETING_CHANNEL_ID is required when GREETING_ENABLED is true"
            )
        greeting_message = os.environ.get(
            "GREETING_MESSAGE", "Agent is now online and ready."
        ).strip()
        goodbye_message = os.environ.get(
            "GOODBYE_MESSAGE", "Agent is shutting down. Goodbye."
        ).strip()

        return cls(
            mm_url=mm_url,
            mm_token=mm_token,
            mm_port=int(os.environ.get("MM_PORT", "8065")),
            mm_scheme=os.environ.get("MM_SCHEME", "http").strip(),
            bot_mention_name=os.environ.get("BOT_MENTION_NAME", "ai-agent").strip(),
            agent_type=agent_type,
            opencode_base_url=opencode_base_url,
            opencode_session_id=opencode_session_id,
            opencode_model_id=opencode_model_id,
            opencode_provider_id=opencode_provider_id,
            copilot_session_id=copilot_session_id,
            copilot_model=copilot_model,
            greeting_enabled=greeting_enabled,
            greeting_channel_id=greeting_channel_id,
            greeting_message=greeting_message,
            goodbye_message=goodbye_message,
        )
