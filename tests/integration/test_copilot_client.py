"""Integration tests: CopilotClient internals (mocking github-copilot-sdk)."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mm_agent_bridge.clients import CopilotClient


# ---------------------------------------------------------------------------
# Helpers to build fake SDK responses
# ---------------------------------------------------------------------------


@dataclass
class _FakeAssistantMessageData:
    """Mimics ``copilot.generated.session_events.AssistantMessageData``."""
    content: str
    message_id: str = "msg-1"


@dataclass
class _FakeSessionEvent:
    """Mimics ``copilot.generated.session_events.SessionEvent``."""
    data: _FakeAssistantMessageData


def _make_response(content: str = "Hello from Copilot!") -> _FakeSessionEvent:
    return _FakeSessionEvent(data=_FakeAssistantMessageData(content=content))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_copilot_sdk(monkeypatch: pytest.MonkeyPatch):
    """Patch the Copilot SDK classes used by CopilotClient.

    Returns a container with references to the mock session so tests
    can inspect calls and configure return values.
    """
    mock_session = AsyncMock()
    mock_session.session_id = "test-session-id"
    mock_session.send_and_wait = AsyncMock(return_value=_make_response())
    mock_session.disconnect = AsyncMock()

    mock_sdk_client = AsyncMock()
    mock_sdk_client.start = AsyncMock()
    mock_sdk_client.stop = AsyncMock()
    mock_sdk_client.create_session = AsyncMock(return_value=mock_session)
    mock_sdk_client.resume_session = AsyncMock(return_value=mock_session)

    # Patch the SDK imports inside the copilot module.
    monkeypatch.setattr(
        "mm_agent_bridge.clients.copilot.SdkClient",
        lambda *args, **kwargs: mock_sdk_client,
    )

    return _SdkMockContainer(
        sdk_client=mock_sdk_client,
        session=mock_session,
    )


@dataclass
class _SdkMockContainer:
    sdk_client: AsyncMock
    session: AsyncMock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCopilotChat:
    """Verify CopilotClient.chat() interacts with the SDK correctly."""

    @pytest.mark.asyncio
    async def test_single_message(self, mock_copilot_sdk) -> None:
        client = CopilotClient(session_id="sess-123", model="gpt-5.4")
        result = await client.chat("hello")
        assert result == "Hello from Copilot!"

    @pytest.mark.asyncio
    async def test_lazy_session_creation(self, mock_copilot_sdk) -> None:
        """SDK client and session are created on first chat() call."""
        client = CopilotClient(session_id="sess-123", model="gpt-5.4")

        # Before chat: nothing started.
        mock_copilot_sdk.sdk_client.start.assert_not_awaited()
        mock_copilot_sdk.sdk_client.resume_session.assert_not_awaited()

        await client.chat("hello")

        # After chat: started and session resumed.
        mock_copilot_sdk.sdk_client.start.assert_awaited_once()
        mock_copilot_sdk.sdk_client.resume_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_session_reused(self, mock_copilot_sdk) -> None:
        """Multiple chat() calls reuse the same session."""
        client = CopilotClient(session_id="sess-123", model="gpt-5.4")
        await client.chat("first")
        await client.chat("second")

        # Session resumed only once.
        mock_copilot_sdk.sdk_client.resume_session.assert_awaited_once()
        # But send_and_wait called twice.
        assert mock_copilot_sdk.session.send_and_wait.await_count == 2

    @pytest.mark.asyncio
    async def test_sends_text_to_session(self, mock_copilot_sdk) -> None:
        client = CopilotClient(session_id="sess-123", model="gpt-5.4")
        await client.chat("explain auth.py")

        mock_copilot_sdk.session.send_and_wait.assert_awaited_once()
        call_args = mock_copilot_sdk.session.send_and_wait.call_args
        assert call_args.args[0] == "explain auth.py"

    @pytest.mark.asyncio
    async def test_timeout_passed_to_send(self, mock_copilot_sdk) -> None:
        client = CopilotClient(session_id="sess-123", model="gpt-5.4", timeout=30.0)
        await client.chat("hello")

        call_kwargs = mock_copilot_sdk.session.send_and_wait.call_args.kwargs
        assert call_kwargs["timeout"] == 30.0

    @pytest.mark.asyncio
    async def test_none_response(self, mock_copilot_sdk) -> None:
        mock_copilot_sdk.session.send_and_wait.return_value = None
        client = CopilotClient(session_id="sess-123", model="gpt-5.4")
        result = await client.chat("hello")
        assert "no response" in result.lower()

    @pytest.mark.asyncio
    async def test_empty_content(self, mock_copilot_sdk) -> None:
        mock_copilot_sdk.session.send_and_wait.return_value = _make_response("")
        client = CopilotClient(session_id="sess-123", model="gpt-5.4")
        result = await client.chat("hello")
        assert "empty response" in result.lower()

    @pytest.mark.asyncio
    async def test_model_passed_to_resume_session(self, mock_copilot_sdk) -> None:
        client = CopilotClient(session_id="sess-123", model="claude-sonnet-4")
        await client.chat("hello")

        call_kwargs = mock_copilot_sdk.sdk_client.resume_session.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4"

    @pytest.mark.asyncio
    async def test_default_model(self, mock_copilot_sdk) -> None:
        """Default model is gpt-5.4 when not specified."""
        client = CopilotClient(session_id="sess-123")
        await client.chat("hello")

        call_kwargs = mock_copilot_sdk.sdk_client.resume_session.call_args.kwargs
        assert call_kwargs["model"] == "gpt-5.4"


class TestCopilotResumeSession:
    """Verify CopilotClient uses resume_session with session_id."""

    @pytest.mark.asyncio
    async def test_resume_with_session_id(self, mock_copilot_sdk) -> None:
        """When session_id is provided, resume_session is called."""
        client = CopilotClient(session_id="existing-sess-456", model="gpt-5.4")
        await client.chat("hello")

        mock_copilot_sdk.sdk_client.resume_session.assert_awaited_once()
        call_args = mock_copilot_sdk.sdk_client.resume_session.call_args
        assert call_args.args[0] == "existing-sess-456"

        # create_session should NOT be called.
        mock_copilot_sdk.sdk_client.create_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_without_session_id(self, mock_copilot_sdk) -> None:
        """When session_id is empty, create_session is called."""
        client = CopilotClient(session_id="", model="gpt-5.4")
        await client.chat("hello")

        mock_copilot_sdk.sdk_client.create_session.assert_awaited_once()
        # resume_session should NOT be called.
        mock_copilot_sdk.sdk_client.resume_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_session_id_passed_correctly(self, mock_copilot_sdk) -> None:
        """The exact session_id is forwarded to resume_session."""
        client = CopilotClient(session_id="my-custom-session-id")
        await client.chat("test")

        call_args = mock_copilot_sdk.sdk_client.resume_session.call_args
        assert call_args.args[0] == "my-custom-session-id"

    @pytest.mark.asyncio
    async def test_fallback_to_create_on_resume_failure(self, mock_copilot_sdk) -> None:
        """When resume_session raises, fallback to create_session."""
        mock_copilot_sdk.sdk_client.resume_session.side_effect = RuntimeError(
            "session not found"
        )
        client = CopilotClient(session_id="bad-session-id", model="gpt-5.4")
        result = await client.chat("hello")

        # resume_session was attempted.
        mock_copilot_sdk.sdk_client.resume_session.assert_awaited_once()
        # Fell back to create_session.
        mock_copilot_sdk.sdk_client.create_session.assert_awaited_once()
        # Chat still works.
        assert result == "Hello from Copilot!"


class TestCopilotStop:
    """Verify CopilotClient.stop() lifecycle management."""

    @pytest.mark.asyncio
    async def test_stop_after_chat(self, mock_copilot_sdk) -> None:
        client = CopilotClient(session_id="sess-123", model="gpt-5.4")
        await client.chat("hello")
        await client.stop()

        mock_copilot_sdk.session.disconnect.assert_awaited_once()
        mock_copilot_sdk.sdk_client.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_before_start_is_safe(self, mock_copilot_sdk) -> None:
        """stop() on an unused client should not raise."""
        client = CopilotClient(session_id="sess-123", model="gpt-5.4")
        await client.stop()  # should not raise
