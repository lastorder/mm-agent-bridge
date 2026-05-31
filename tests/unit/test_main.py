"""Unit tests for the CLI entry point."""

from __future__ import annotations

import signal

import pytest

from mm_agent_bridge import main


class TestMain:
    def test_sigterm_handler_exits_without_duplicate_goodbye(self, monkeypatch) -> None:
        events: dict[str, object] = {}
        fake_config = type("FakeConfig", (), {"agent_type": "opencode"})()

        class _FakeBot:
            def run(self) -> None:
                handler = events["handler"]
                with pytest.raises(SystemExit) as excinfo:
                    handler(signal.SIGTERM, None)
                assert excinfo.value.code == 0

        fake_bot = _FakeBot()

        monkeypatch.setattr(main, "load_dotenv", lambda: None)
        monkeypatch.setattr(main.Config, "from_env", classmethod(lambda cls: fake_config))
        monkeypatch.setattr(main, "AgentBridge", lambda config: fake_bot)
        monkeypatch.setattr(
            main.signal,
            "signal",
            lambda sig, handler: events.update({"signal": sig, "handler": handler}),
        )

        main.main()

        assert events["signal"] == signal.SIGTERM
