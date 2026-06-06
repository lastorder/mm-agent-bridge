"""Integration tests: OpenCodeClient internals — _send_message and _extract_response."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mm_agent_bridge.clients import OpenCodeClient
from tests.conftest import make_assistant_message_json, make_user_message_json


class TestExtractResponse:
    """Verify _extract_response parses the API JSON correctly."""

    @pytest.fixture
    def client(self, mock_sdk_messages) -> OpenCodeClient:
        c = OpenCodeClient(
            base_url="http://localhost:36000",
            session_id="test-session-id",
            model_id="test-model",
            provider_id="test-provider",
        )
        c._sdk = mock_sdk_messages.sdk
        return c

    @pytest.mark.asyncio
    async def test_single_part(self, client, mock_sdk_messages) -> None:
        msg_id = "resp-1"
        mock_sdk_messages.response_json = [
            make_user_message_json("hello"),
            make_assistant_message_json("single answer", msg_id=msg_id),
        ]

        text = await client._extract_response(msg_id)
        assert text == "single answer"

    @pytest.mark.asyncio
    async def test_multiple_parts(self, client, mock_sdk_messages) -> None:
        msg_id = "resp-2"
        mock_sdk_messages.response_json = [
            make_assistant_message_json("part one", "part two", msg_id=msg_id),
        ]

        text = await client._extract_response(msg_id)
        assert text == "part one\npart two"

    @pytest.mark.asyncio
    async def test_message_not_found(self, client, mock_sdk_messages) -> None:
        """When message ID doesn't match any item, return an error string."""
        mock_sdk_messages.response_json = [
            make_user_message_json("hey"),
            make_assistant_message_json("some answer", msg_id="other-id"),
        ]

        text = await client._extract_response("nonexistent-id")
        assert "not found" in text.lower()

    @pytest.mark.asyncio
    async def test_no_messages(self, client, mock_sdk_messages) -> None:
        mock_sdk_messages.response_json = []
        text = await client._extract_response("any-id")
        assert "not found" in text.lower()

    @pytest.mark.asyncio
    async def test_empty_message_id(self, client) -> None:
        """When no message ID is provided, return an error string."""
        text = await client._extract_response("")
        assert "missing" in text.lower()

    @pytest.mark.asyncio
    async def test_message_with_error_raises(self, client, mock_sdk_messages) -> None:
        """When the matched message has an LLM error, raise RuntimeError."""
        error_msg = {
            "info": {
                "id": "err-msg-1",
                "role": "assistant",
                "error": {
                    "name": "APIError",
                    "data": {
                        "message": "The requested model is not supported.",
                        "statusCode": 400,
                    },
                },
            },
            "parts": [],
        }
        mock_sdk_messages.response_json = [
            make_user_message_json("hello"),
            error_msg,
        ]

        with pytest.raises(RuntimeError, match="model is not supported"):
            await client._extract_response("err-msg-1")


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

        mock_opencode.chat.assert_awaited_once_with("@user-u1: refactor auth module")


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

        # Error updates the ack post via patch_post.
        mock_driver.posts.patch_post.assert_called_once()
        patch_opts = mock_driver.posts.patch_post.call_args.kwargs["options"]
        assert "error" in patch_opts["message"].lower()

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

        # Error updates the ack post via patch_post.
        mock_driver.posts.patch_post.assert_called_once()
        patch_opts = mock_driver.posts.patch_post.call_args.kwargs["options"]
        assert "error" in patch_opts["message"].lower()
        assert bot._busy is False


class TestOpenCodeSessionFallback:
    """Verify OpenCodeClient creates a new session when existing one is unavailable."""

    @pytest.mark.asyncio
    async def test_valid_session_is_reused(self, mock_sdk_messages) -> None:
        """When the session exists, it's used directly (no create call)."""
        client = OpenCodeClient(
            base_url="http://localhost:36000",
            session_id="existing-session",
            model_id="test-model",
            provider_id="test-provider",
        )
        client._sdk = mock_sdk_messages.sdk
        # mock_sdk_messages makes messages() return 200 — session is valid.
        await client._ensure_session()

        assert client._session_id == "existing-session"
        assert client._session_validated is True

    @pytest.mark.asyncio
    async def test_invalid_session_creates_new(self) -> None:
        """When the session returns an error, a new one is created."""
        fake_session = MagicMock()
        fake_session.id = "new-session-id-abc"

        mock_sdk = MagicMock()
        # messages() raises — session is invalid.
        mock_sdk.session.with_raw_response.messages = AsyncMock(
            side_effect=Exception("session not found"),
        )
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


class TestVariant:
    """Verify variant is passed via extra_body."""

    @pytest.mark.asyncio
    async def test_variant_in_extra_body(self) -> None:
        """When variant is set, extra_body includes it."""
        mock_raw = AsyncMock()
        mock_raw.json = AsyncMock(return_value={
            "info": {"id": "msg-1", "role": "assistant"},
            "parts": [{"type": "text", "text": "ok"}],
        })
        mock_sdk = MagicMock()
        mock_sdk.session.with_raw_response.chat = AsyncMock(return_value=mock_raw)

        client = OpenCodeClient(
            base_url="http://localhost:36000",
            session_id="s1",
            model_id="m1",
            provider_id="p1",
            variant="low",
        )
        client._sdk = mock_sdk
        client._session_validated = True

        await client.chat("hello")

        call_kwargs = mock_sdk.session.with_raw_response.chat.call_args.kwargs
        assert call_kwargs["extra_body"] == {"variant": "low"}

    @pytest.mark.asyncio
    async def test_no_variant_no_extra_body(self) -> None:
        """When variant is empty, extra_body is None."""
        mock_raw = AsyncMock()
        mock_raw.json = AsyncMock(return_value={
            "info": {"id": "msg-1", "role": "assistant"},
            "parts": [{"type": "text", "text": "ok"}],
        })
        mock_sdk = MagicMock()
        mock_sdk.session.with_raw_response.chat = AsyncMock(return_value=mock_raw)

        client = OpenCodeClient(
            base_url="http://localhost:36000",
            session_id="s1",
            model_id="m1",
            provider_id="p1",
        )
        client._sdk = mock_sdk
        client._session_validated = True

        await client.chat("hello")

        call_kwargs = mock_sdk.session.with_raw_response.chat.call_args.kwargs
        assert call_kwargs.get("extra_body") is None


class TestPersistEnv:
    """Verify .env persistence for session and provider/model."""

    @pytest.mark.asyncio
    async def test_new_session_persisted(self) -> None:
        """When a new session is created, OPENCODE_SESSION_ID is written to .env."""
        fake_session = MagicMock()
        fake_session.id = "new-sess-xyz"

        mock_sdk = MagicMock()
        mock_sdk.session.create = AsyncMock(return_value=fake_session)

        client = OpenCodeClient(
            base_url="http://localhost:36000",
            session_id="",
            model_id="m1",
            provider_id="p1",
        )
        client._sdk = mock_sdk

        with patch("mm_agent_bridge.clients.opencode._persist_env") as mock_persist:
            await client._ensure_session()

            mock_persist.assert_called_once_with("OPENCODE_SESSION_ID", "new-sess-xyz")


class TestBasicAuth:
    """Verify Basic Auth headers are injected when password is set."""

    def test_auth_headers_when_password_set(self) -> None:
        """SDK is created with Basic Auth headers."""
        with patch("mm_agent_bridge.clients.opencode.AsyncOpencode") as mock_cls:
            OpenCodeClient(
                base_url="http://localhost:4096",
                password="secret",
                username="admin",
            )

            mock_cls.assert_called_once()
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["base_url"] == "http://localhost:4096"
            assert "Authorization" in call_kwargs["default_headers"]
            import base64
            expected = base64.b64encode(b"admin:secret").decode()
            assert call_kwargs["default_headers"]["Authorization"] == f"Basic {expected}"

    def test_no_auth_headers_without_password(self) -> None:
        """SDK is created without auth headers when no password."""
        with patch("mm_agent_bridge.clients.opencode.AsyncOpencode") as mock_cls:
            OpenCodeClient(base_url="http://localhost:4096")

            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs.get("default_headers") is None
