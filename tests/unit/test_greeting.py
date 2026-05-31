"""Unit tests for greeting/goodbye and ack-then-update behavior."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mm_agent_bridge.bot import AgentBridge
from mm_agent_bridge.config import Config

from tests.conftest import BOT_USER_ID


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def greeting_config() -> Config:
    """Config with greeting enabled."""
    return Config(
        mm_url="localhost",
        mm_token="test-token",
        mm_port=8065,
        mm_scheme="http",
        agent_type="opencode",
        opencode_base_url="http://localhost:36000",
        opencode_session_id="test-session-id",
        opencode_model_id="test-model",
        opencode_provider_id="test-provider",
        greeting_enabled=True,
        greeting_channel_id="ch-greet",
        greeting_message="Hello, I am online!",
        goodbye_message="Goodbye, shutting down!",
    )


@pytest.fixture
def greeting_bot(
    greeting_config: Config, mock_driver: MagicMock, mock_opencode: AsyncMock
) -> AgentBridge:
    """AgentBridge with greeting enabled and mocked deps."""
    b = AgentBridge.__new__(AgentBridge)
    b.config = greeting_config
    b.driver = mock_driver
    b.opencode = mock_opencode
    b.bot_user_id = BOT_USER_ID
    b._busy = False
    b.queue = asyncio.Queue()
    return b


# ---------------------------------------------------------------------------
# Greeting / Goodbye
# ---------------------------------------------------------------------------


class TestSendGreeting:
    """Tests for AgentBridge._send_greeting()."""

    def test_posts_greeting_when_enabled(self, greeting_bot, mock_driver) -> None:
        with patch("mm_agent_bridge.bot.socket.gethostname", return_value="host-1"):
            greeting_bot._send_greeting()

        mock_driver.posts.create_post.assert_called_once_with(
            options={
                "channel_id": "ch-greet",
                "message": "Hello, I am online! (host: host-1)",
            }
        )

    def test_no_post_when_disabled(self, bot, mock_driver) -> None:
        """Default config has greeting_enabled=False."""
        bot._send_greeting()

        mock_driver.posts.create_post.assert_not_called()


class TestSendGoodbye:
    """Tests for AgentBridge._send_goodbye()."""

    def test_posts_goodbye_when_enabled(self, greeting_bot, mock_driver) -> None:
        with patch("mm_agent_bridge.bot.socket.gethostname", return_value="host-1"):
            greeting_bot._send_goodbye()

        mock_driver.posts.create_post.assert_called_once_with(
            options={
                "channel_id": "ch-greet",
                "message": "Goodbye, shutting down! (host: host-1)",
            }
        )

    def test_no_post_when_disabled(self, bot, mock_driver) -> None:
        bot._send_goodbye()

        mock_driver.posts.create_post.assert_not_called()


# ---------------------------------------------------------------------------
# Ack-then-update pattern
# ---------------------------------------------------------------------------


class TestAckThenUpdate:
    """Tests for the acknowledgment → update flow in _process_post."""

    @pytest.mark.asyncio
    async def test_ack_posted_before_chat(self, bot, mock_driver, mock_opencode) -> None:
        """An ack message is posted before calling agent.chat()."""
        call_order: list[str] = []

        def track_create_post(**kwargs):
            call_order.append("create_post")
            return {"id": "ack-post-id"}

        async def track_chat(*args, **kwargs):
            call_order.append("chat")
            return "response"

        mock_driver.posts.create_post.side_effect = track_create_post
        mock_opencode.chat = track_chat

        post = {
            "id": "p1",
            "channel_id": "ch-1",
            "user_id": "u1",
            "message": "@ai-agent hello",
            "root_id": "",
        }
        await bot._process_post(post)

        assert call_order == ["create_post", "chat"]

    @pytest.mark.asyncio
    async def test_ack_message_content(self, bot, mock_driver, mock_opencode) -> None:
        """The ack message says 'Processing your request...'."""
        post = {
            "id": "p1",
            "channel_id": "ch-1",
            "user_id": "u1",
            "message": "@ai-agent test",
            "root_id": "",
        }
        await bot._process_post(post)

        ack_opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert ack_opts["message"] == "Processing your request..."

    @pytest.mark.asyncio
    async def test_response_updates_ack_post(self, bot, mock_driver, mock_opencode) -> None:
        """On success, the ack post is updated with the actual response."""
        mock_driver.posts.create_post.return_value = {"id": "ack-id-xyz"}
        mock_opencode.chat.return_value = "Final answer."

        post = {
            "id": "p1",
            "channel_id": "ch-1",
            "user_id": "u1",
            "message": "@ai-agent question",
            "root_id": "",
        }
        await bot._process_post(post)

        mock_driver.posts.patch_post.assert_called_once_with(
            "ack-id-xyz", options={"message": "Final answer."}
        )

    @pytest.mark.asyncio
    async def test_error_updates_ack_post(self, bot, mock_driver, mock_opencode) -> None:
        """On error, the ack post is updated with error text."""
        mock_driver.posts.create_post.return_value = {"id": "ack-id-err"}
        mock_opencode.chat.side_effect = RuntimeError("boom")

        post = {
            "id": "p1",
            "channel_id": "ch-1",
            "user_id": "u1",
            "message": "@ai-agent fail",
            "root_id": "",
        }
        await bot._process_post(post)

        mock_driver.posts.patch_post.assert_called_once()
        patch_opts = mock_driver.posts.patch_post.call_args.kwargs["options"]
        assert "error" in patch_opts["message"].lower()
        # The ack post ID should match.
        assert mock_driver.posts.patch_post.call_args.args[0] == "ack-id-err"

    @pytest.mark.asyncio
    async def test_empty_message_no_ack(self, bot, mock_driver, mock_opencode) -> None:
        """Empty text after cleaning mention should NOT post an ack."""
        post = {
            "id": "p1",
            "channel_id": "ch-1",
            "user_id": "u1",
            "message": "@ai-agent",
            "root_id": "",
        }
        await bot._process_post(post)

        # Only the "empty message" notice, not an ack.
        mock_driver.posts.create_post.assert_called_once()
        opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert "empty" in opts["message"].lower()
        # No patch_post call since no ack was posted.
        mock_driver.posts.patch_post.assert_not_called()
