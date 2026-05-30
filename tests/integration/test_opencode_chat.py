"""Integration tests: OpenCodeClient internals — _send_message and _extract_response."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mm_agent_bridge.clients import OpenCodeClient
from tests.conftest import make_assistant_message_json, make_user_message_json


class TestExtractResponse:
    """Verify _extract_response parses the API JSON correctly."""

    @pytest.fixture
    def client(self) -> OpenCodeClient:
        return OpenCodeClient(
            base_url="http://localhost:36000",
            session_id="test-session-id",
            model_id="test-model",
            provider_id="test-provider",
        )

    @pytest.mark.asyncio
    async def test_single_part(self, client, mock_httpx_messages) -> None:
        msg_id = "resp-1"
        mock_httpx_messages.response_json = [
            make_user_message_json("hello"),
            make_assistant_message_json("single answer", msg_id=msg_id),
        ]

        text = await client._extract_response(msg_id)
        assert text == "single answer"

    @pytest.mark.asyncio
    async def test_multiple_parts(self, client, mock_httpx_messages) -> None:
        msg_id = "resp-2"
        mock_httpx_messages.response_json = [
            make_assistant_message_json("part one", "part two", msg_id=msg_id),
        ]

        text = await client._extract_response(msg_id)
        assert text == "part one\npart two"

    @pytest.mark.asyncio
    async def test_fallback_to_latest_assistant(self, client, mock_httpx_messages) -> None:
        """When message ID doesn't match, fall back to last assistant message."""
        mock_httpx_messages.response_json = [
            make_user_message_json("hey"),
            make_assistant_message_json("fallback answer", msg_id="other-id"),
        ]

        text = await client._extract_response("nonexistent-id")
        assert text == "fallback answer"

    @pytest.mark.asyncio
    async def test_no_messages(self, client, mock_httpx_messages) -> None:
        mock_httpx_messages.response_json = []
        text = await client._extract_response("any-id")
        assert "no response" in text.lower()


class TestChatPayload:
    """Verify that chat() passes the correct args through to the SDK."""

    @pytest.mark.asyncio
    async def test_sends_correct_payload(self, bot, mock_opencode) -> None:
        post = {
            "id": "p1",
            "channel_id": "ch-1",
            "user_id": "u1",
            "message": "@ai-agent refactor auth module",
            "root_id": "",
        }
        await bot._process_post(post)

        mock_opencode.chat.assert_awaited_once_with("refactor auth module")


class TestChatErrorHandling:
    """Verify error handling at the bot level."""

    @pytest.mark.asyncio
    async def test_timeout_handling(self, bot, mock_driver, mock_opencode) -> None:
        """Timeout during chat should result in an error reply."""
        mock_opencode.chat.side_effect = TimeoutError("timed out")

        post = {
            "id": "p1",
            "channel_id": "ch-1",
            "user_id": "u1",
            "message": "@ai-agent slow task",
            "root_id": "",
        }
        await bot._process_post(post)

        opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert "error" in opts["message"].lower()

    @pytest.mark.asyncio
    async def test_api_error_handling(self, bot, mock_driver, mock_opencode) -> None:
        """API errors from OpenCode should be caught and reported."""
        mock_opencode.chat.side_effect = Exception("API auth failed")

        post = {
            "id": "p1",
            "channel_id": "ch-1",
            "user_id": "u1",
            "message": "@ai-agent do something",
            "root_id": "",
        }
        await bot._process_post(post)

        opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert "error" in opts["message"].lower()
        assert bot._busy is False


class TestOpenCodeSessionFallback:
    """Verify OpenCodeClient creates a new session when existing one is unavailable."""

    @pytest.mark.asyncio
    async def test_valid_session_is_reused(self, mock_httpx_messages) -> None:
        """When the session exists, it's used directly (no create call)."""
        client = OpenCodeClient(
            base_url="http://localhost:36000",
            session_id="existing-session",
            model_id="test-model",
            provider_id="test-provider",
        )
        # mock_httpx_messages makes GET return 200 — session is valid.
        await client._ensure_session()

        assert client._session_id == "existing-session"
        assert client._session_validated is True

    @pytest.mark.asyncio
    async def test_invalid_session_creates_new(self, monkeypatch) -> None:
        """When the session returns an error, a new one is created."""
        # Mock httpx to return 404 for the session check.
        class _FakeResponse:
            status_code = 404

            def raise_for_status(self):
                from httpx import HTTPStatusError, Request, Response

                raise HTTPStatusError(
                    "Not Found",
                    request=Request("GET", "http://x"),
                    response=Response(404),
                )

        class _FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def get(self, url, **kwargs):
                return _FakeResponse()

        monkeypatch.setattr(
            "mm_agent_bridge.clients.opencode.httpx.AsyncClient", _FakeAsyncClient
        )

        # Mock the SDK session.create() to return a fake session.
        fake_session = MagicMock()
        fake_session.id = "new-session-id-abc"

        mock_sdk = MagicMock()
        mock_sdk.session.create = AsyncMock(return_value=fake_session)

        client = OpenCodeClient(
            base_url="http://localhost:36000",
            session_id="dead-session",
            model_id="test-model",
            provider_id="test-provider",
        )
        client._sdk = mock_sdk

        await client._ensure_session()

        # New session was created.
        mock_sdk.session.create.assert_awaited_once()
        assert client._session_id == "new-session-id-abc"
        assert client._session_validated is True

    @pytest.mark.asyncio
    async def test_empty_session_id_creates_new(self, monkeypatch) -> None:
        """When no session_id is configured, a new session is created."""
        fake_session = MagicMock()
        fake_session.id = "brand-new-session"

        mock_sdk = MagicMock()
        mock_sdk.session.create = AsyncMock(return_value=fake_session)

        client = OpenCodeClient(
            base_url="http://localhost:36000",
            session_id="",
            model_id="test-model",
            provider_id="test-provider",
        )
        client._sdk = mock_sdk

        await client._ensure_session()

        mock_sdk.session.create.assert_awaited_once()
        assert client._session_id == "brand-new-session"
        assert client._session_validated is True
