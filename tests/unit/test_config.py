"""Unit tests for mm_agent_bridge.config.Config."""

from __future__ import annotations

import pytest

from mm_agent_bridge.config import Config, CopilotConfig, OpenCodeConfig


def _set_opencode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set all env vars required for the default (opencode) agent."""
    monkeypatch.setenv("MM_URL", "localhost")
    monkeypatch.setenv("MM_TOKEN", "tok")
    monkeypatch.setenv("OPENCODE_BASE_URL", "http://localhost:36000")
    monkeypatch.setenv("OPENCODE_MODEL_ID", "model-1")
    monkeypatch.setenv("OPENCODE_PROVIDER_ID", "provider-1")


class TestConfigFromEnv:
    """Tests for Config.from_env()."""

    def test_all_required_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MM_URL", "mattermost.local")
        monkeypatch.setenv("MM_TOKEN", "tok-abc")
        monkeypatch.setenv("OPENCODE_BASE_URL", "http://localhost:4096")
        monkeypatch.setenv("OPENCODE_SESSION_ID", "sess-1")
        monkeypatch.setenv("OPENCODE_MODEL_ID", "model-1")
        monkeypatch.setenv("OPENCODE_PROVIDER_ID", "provider-1")

        cfg = Config.from_env()

        assert cfg.mm_url == "mattermost.local"
        assert cfg.mm_token == "tok-abc"
        assert cfg.agent_type == "opencode"
        assert cfg.opencode is not None
        assert cfg.opencode.base_url == "http://localhost:4096"
        assert cfg.opencode.session_id == "sess-1"
        assert cfg.opencode.model_id == "model-1"
        assert cfg.opencode.provider_id == "provider-1"

    @pytest.mark.parametrize("var", ["OPENCODE_MODEL_ID", "OPENCODE_PROVIDER_ID", "OPENCODE_BASE_URL"])
    def test_missing_opencode_required_raises(
        self, monkeypatch: pytest.MonkeyPatch, var: str
    ) -> None:
        """OPENCODE_MODEL_ID, OPENCODE_PROVIDER_ID, OPENCODE_BASE_URL are required."""
        _set_opencode_env(monkeypatch)
        monkeypatch.delenv(var)

        with pytest.raises(ValueError, match=var):
            Config.from_env()

    def test_defaults_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)
        # Do NOT set MM_PORT, MM_SCHEME

        cfg = Config.from_env()

        assert cfg.mm_port == 8065
        assert cfg.mm_scheme == "http"

    def test_custom_port_and_scheme(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("MM_PORT", "443")
        monkeypatch.setenv("MM_SCHEME", "https")

        cfg = Config.from_env()

        assert cfg.mm_port == 443
        assert cfg.mm_scheme == "https"

    @pytest.mark.parametrize("missing_var", ["MM_URL", "MM_TOKEN"])
    def test_missing_common_required_raises(
        self, monkeypatch: pytest.MonkeyPatch, missing_var: str
    ) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.delenv(missing_var, raising=False)

        with pytest.raises(ValueError, match=missing_var):
            Config.from_env()

    def test_opencode_session_id_optional(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OPENCODE_SESSION_ID is optional — new session created at runtime."""
        _set_opencode_env(monkeypatch)
        # No OPENCODE_SESSION_ID set — should NOT raise.

        cfg = Config.from_env()
        assert cfg.opencode is not None
        assert cfg.opencode.session_id == ""

    def test_whitespace_only_treated_as_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("MM_URL", "   ")

        with pytest.raises(ValueError, match="MM_URL"):
            Config.from_env()

    def test_invalid_agent_type_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("AGENT_TYPE", "invalid")

        with pytest.raises(ValueError, match="AGENT_TYPE"):
            Config.from_env()


class TestCopilotConfig:
    """Tests for Config.from_env() with AGENT_TYPE=copilot."""

    def test_copilot_with_session_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MM_URL", "localhost")
        monkeypatch.setenv("MM_TOKEN", "tok")
        monkeypatch.setenv("AGENT_TYPE", "copilot")
        monkeypatch.setenv("COPILOT_SESSION_ID", "sess-abc")

        cfg = Config.from_env()

        assert cfg.agent_type == "copilot"
        assert cfg.copilot is not None
        assert cfg.copilot.session_id == "sess-abc"
        assert cfg.copilot.model == "gpt-5.4"

    def test_copilot_session_id_optional(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """COPILOT_SESSION_ID is optional — new session created at runtime."""
        monkeypatch.setenv("MM_URL", "localhost")
        monkeypatch.setenv("MM_TOKEN", "tok")
        monkeypatch.setenv("AGENT_TYPE", "copilot")
        # No COPILOT_SESSION_ID — should NOT raise.

        cfg = Config.from_env()
        assert cfg.copilot is not None
        assert cfg.copilot.session_id == ""

    def test_copilot_does_not_require_opencode_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When agent_type=copilot, opencode env vars are not required."""
        monkeypatch.setenv("MM_URL", "localhost")
        monkeypatch.setenv("MM_TOKEN", "tok")
        monkeypatch.setenv("AGENT_TYPE", "copilot")
        # No OPENCODE_* vars set — should NOT raise.

        cfg = Config.from_env()
        assert cfg.opencode is None

    def test_copilot_custom_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MM_URL", "localhost")
        monkeypatch.setenv("MM_TOKEN", "tok")
        monkeypatch.setenv("AGENT_TYPE", "copilot")
        monkeypatch.setenv("COPILOT_MODEL", "claude-sonnet-4")

        cfg = Config.from_env()
        assert cfg.copilot is not None
        assert cfg.copilot.model == "claude-sonnet-4"


class TestGreetingConfig:
    """Tests for greeting/goodbye configuration."""

    def test_greeting_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)

        cfg = Config.from_env()

        assert cfg.greeting_enabled is False
        assert cfg.greeting_channel_id == ""

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "YES"])
    def test_greeting_enabled_truthy_values(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("GREETING_ENABLED", value)
        monkeypatch.setenv("GREETING_CHANNEL_ID", "ch-greeting")

        cfg = Config.from_env()

        assert cfg.greeting_enabled is True

    @pytest.mark.parametrize("value", ["false", "False", "0", "no", ""])
    def test_greeting_disabled_falsy_values(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("GREETING_ENABLED", value)

        cfg = Config.from_env()

        assert cfg.greeting_enabled is False

    def test_greeting_enabled_requires_channel_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("GREETING_ENABLED", "true")
        # No GREETING_CHANNEL_ID set.

        with pytest.raises(ValueError, match="GREETING_CHANNEL_ID"):
            Config.from_env()

    def test_greeting_enabled_whitespace_channel_id_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("GREETING_ENABLED", "true")
        monkeypatch.setenv("GREETING_CHANNEL_ID", "   ")

        with pytest.raises(ValueError, match="GREETING_CHANNEL_ID"):
            Config.from_env()

    def test_greeting_channel_not_required_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("GREETING_ENABLED", "false")
        # No GREETING_CHANNEL_ID — should NOT raise.

        cfg = Config.from_env()
        assert cfg.greeting_enabled is False

    def test_default_messages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("GREETING_ENABLED", "true")
        monkeypatch.setenv("GREETING_CHANNEL_ID", "ch-123")

        cfg = Config.from_env()

        assert cfg.greeting_message == "Agent is now online and ready. You can use @ai-agent to request my support."
        assert cfg.goodbye_message == "Agent is shutting down. Goodbye."

    def test_custom_messages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("GREETING_ENABLED", "true")
        monkeypatch.setenv("GREETING_CHANNEL_ID", "ch-123")
        monkeypatch.setenv("GREETING_MESSAGE", "Bot online!")
        monkeypatch.setenv("GOODBYE_MESSAGE", "Bot offline!")

        cfg = Config.from_env()

        assert cfg.greeting_message == "Bot online!"
        assert cfg.goodbye_message == "Bot offline!"

    def test_greeting_message_includes_mention_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default greeting message uses the configured bot mention name."""
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("BOT_MENTION_NAME", "my-bot")

        cfg = Config.from_env()

        assert "@my-bot" in cfg.greeting_message


class TestMessageConfig:
    """Tests for configurable bot messages (MSG_* env vars)."""

    def test_default_messages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)

        cfg = Config.from_env()

        assert cfg.msg_queued == "Your request has been queued. Please wait..."
        assert cfg.msg_processing == "Processing your request..."
        assert cfg.msg_error == "Sorry, an error occurred while processing your request."
        assert cfg.msg_empty == "Empty message after removing mention."
        assert cfg.msg_show_host is True

    def test_custom_messages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("MSG_QUEUED", "Please hold...")
        monkeypatch.setenv("MSG_PROCESSING", "Working on it...")
        monkeypatch.setenv("MSG_ERROR", "Oops, something broke.")
        monkeypatch.setenv("MSG_EMPTY", "Nothing to do.")

        cfg = Config.from_env()

        assert cfg.msg_queued == "Please hold..."
        assert cfg.msg_processing == "Working on it..."
        assert cfg.msg_error == "Oops, something broke."
        assert cfg.msg_empty == "Nothing to do."

    @pytest.mark.parametrize("value", ["true", "True", "1", "yes"])
    def test_msg_show_host_enabled(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("MSG_SHOW_HOST", value)

        cfg = Config.from_env()

        assert cfg.msg_show_host is True


class TestThreadContextConfig:
    """Tests for THREAD_CONTEXT_MAX_MESSAGES env var."""

    def test_default_is_20(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)

        cfg = Config.from_env()

        assert cfg.thread_context_max_messages == 20

    def test_custom_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("THREAD_CONTEXT_MAX_MESSAGES", "50")

        cfg = Config.from_env()

        assert cfg.thread_context_max_messages == 50


class TestQueueConfig:
    """Tests for QUEUE_MAX_SIZE and MSG_QUEUE_FULL env vars."""

    def test_default_queue_max_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)

        cfg = Config.from_env()

        assert cfg.queue_max_size == 10

    def test_custom_queue_max_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("QUEUE_MAX_SIZE", "5")

        cfg = Config.from_env()

        assert cfg.queue_max_size == 5

    def test_default_msg_queue_full(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)

        cfg = Config.from_env()

        assert cfg.msg_queue_full == "Agent is busy, please try again later."

    def test_custom_msg_queue_full(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("MSG_QUEUE_FULL", "Too many requests!")

        cfg = Config.from_env()

        assert cfg.msg_queue_full == "Too many requests!"


class TestOpenCodeVariantConfig:
    """Tests for OPENCODE_VARIANT env var."""

    def test_default_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)

        cfg = Config.from_env()

        assert cfg.opencode is not None
        assert cfg.opencode.variant == ""

    def test_custom_variant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("OPENCODE_VARIANT", "low")

        cfg = Config.from_env()

        assert cfg.opencode is not None
        assert cfg.opencode.variant == "low"


class TestOpenCodeAuthConfig:
    """Tests for OPENCODE_SERVER_PASSWORD / OPENCODE_SERVER_USERNAME."""

    def test_password_default_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.delenv("OPENCODE_SERVER_PASSWORD", raising=False)

        cfg = Config.from_env()

        assert cfg.opencode is not None
        assert cfg.opencode.password == ""

    def test_username_default_opencode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.delenv("OPENCODE_SERVER_USERNAME", raising=False)

        cfg = Config.from_env()

        assert cfg.opencode is not None
        assert cfg.opencode.username == "opencode"

    def test_custom_password_and_username(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("OPENCODE_SERVER_PASSWORD", "secret123")
        monkeypatch.setenv("OPENCODE_SERVER_USERNAME", "admin")

        cfg = Config.from_env()

        assert cfg.opencode is not None
        assert cfg.opencode.password == "secret123"
        assert cfg.opencode.username == "admin"

    def test_base_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)

        cfg = Config.from_env()

        assert cfg.opencode is not None
        assert cfg.opencode.base_url == "http://localhost:36000"

    def test_custom_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)
        monkeypatch.setenv("OPENCODE_BASE_URL", "http://remote:4096")

        cfg = Config.from_env()

        assert cfg.opencode is not None
        assert cfg.opencode.base_url == "http://remote:4096"


class TestOpenCodeConfigFromEnv:
    """Tests for OpenCodeConfig.from_env() standalone."""

    def test_reads_all_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENCODE_BASE_URL", "http://host:1234")
        monkeypatch.setenv("OPENCODE_MODEL_ID", "my-model")
        monkeypatch.setenv("OPENCODE_PROVIDER_ID", "my-provider")
        monkeypatch.setenv("OPENCODE_SESSION_ID", "sess-x")
        monkeypatch.setenv("OPENCODE_VARIANT", "high")
        monkeypatch.setenv("OPENCODE_SERVER_PASSWORD", "pw")
        monkeypatch.setenv("OPENCODE_SERVER_USERNAME", "usr")

        oc = OpenCodeConfig.from_env()

        assert oc.base_url == "http://host:1234"
        assert oc.model_id == "my-model"
        assert oc.provider_id == "my-provider"
        assert oc.session_id == "sess-x"
        assert oc.variant == "high"
        assert oc.password == "pw"
        assert oc.username == "usr"

    def test_missing_required_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENCODE_BASE_URL", "http://host:1234")
        monkeypatch.delenv("OPENCODE_MODEL_ID", raising=False)
        monkeypatch.delenv("OPENCODE_PROVIDER_ID", raising=False)

        with pytest.raises(ValueError, match="OPENCODE_MODEL_ID"):
            OpenCodeConfig.from_env()


class TestCopilotConfigFromEnv:
    """Tests for CopilotConfig.from_env() standalone."""

    def test_reads_all_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COPILOT_SESSION_ID", "cp-sess")
        monkeypatch.setenv("COPILOT_MODEL", "claude-sonnet-4")

        cc = CopilotConfig.from_env()

        assert cc.session_id == "cp-sess"
        assert cc.model == "claude-sonnet-4"

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_SESSION_ID", raising=False)
        monkeypatch.delenv("COPILOT_MODEL", raising=False)

        cc = CopilotConfig.from_env()

        assert cc.session_id == ""
        assert cc.model == "gpt-5.4"
