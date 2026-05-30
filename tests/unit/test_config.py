"""Unit tests for mm_agent_bridge.config.Config."""

from __future__ import annotations

import pytest

from mm_agent_bridge.config import Config


def _set_opencode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set all env vars required for the default (opencode) agent."""
    monkeypatch.setenv("MM_URL", "localhost")
    monkeypatch.setenv("MM_TOKEN", "tok")
    monkeypatch.setenv("OPENCODE_MODEL_ID", "m")
    monkeypatch.setenv("OPENCODE_PROVIDER_ID", "p")


class TestConfigFromEnv:
    """Tests for Config.from_env()."""

    def test_all_required_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MM_URL", "mattermost.local")
        monkeypatch.setenv("MM_TOKEN", "tok-abc")
        monkeypatch.setenv("OPENCODE_SESSION_ID", "sess-1")
        monkeypatch.setenv("OPENCODE_MODEL_ID", "model-1")
        monkeypatch.setenv("OPENCODE_PROVIDER_ID", "provider-1")

        cfg = Config.from_env()

        assert cfg.mm_url == "mattermost.local"
        assert cfg.mm_token == "tok-abc"
        assert cfg.agent_type == "opencode"
        assert cfg.opencode_session_id == "sess-1"
        assert cfg.opencode_model_id == "model-1"
        assert cfg.opencode_provider_id == "provider-1"

    def test_defaults_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_opencode_env(monkeypatch)
        # Do NOT set MM_PORT, MM_SCHEME, OPENCODE_BASE_URL

        cfg = Config.from_env()

        assert cfg.mm_port == 8065
        assert cfg.mm_scheme == "http"
        assert cfg.opencode_base_url == "http://localhost:36000"

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

    @pytest.mark.parametrize(
        "missing_var",
        ["OPENCODE_MODEL_ID", "OPENCODE_PROVIDER_ID"],
    )
    def test_missing_opencode_required_raises(
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
        assert cfg.opencode_session_id == ""

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
        assert cfg.copilot_session_id == "sess-abc"
        assert cfg.copilot_model == "gpt-5.4"

    def test_copilot_session_id_optional(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """COPILOT_SESSION_ID is optional — new session created at runtime."""
        monkeypatch.setenv("MM_URL", "localhost")
        monkeypatch.setenv("MM_TOKEN", "tok")
        monkeypatch.setenv("AGENT_TYPE", "copilot")
        # No COPILOT_SESSION_ID — should NOT raise.

        cfg = Config.from_env()
        assert cfg.copilot_session_id == ""

    def test_copilot_does_not_require_opencode_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When agent_type=copilot, opencode env vars are not required."""
        monkeypatch.setenv("MM_URL", "localhost")
        monkeypatch.setenv("MM_TOKEN", "tok")
        monkeypatch.setenv("AGENT_TYPE", "copilot")
        # No OPENCODE_* vars set — should NOT raise.

        cfg = Config.from_env()
        assert cfg.opencode_session_id == ""

    def test_copilot_custom_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MM_URL", "localhost")
        monkeypatch.setenv("MM_TOKEN", "tok")
        monkeypatch.setenv("AGENT_TYPE", "copilot")
        monkeypatch.setenv("COPILOT_MODEL", "claude-sonnet-4")

        cfg = Config.from_env()
        assert cfg.copilot_model == "claude-sonnet-4"
