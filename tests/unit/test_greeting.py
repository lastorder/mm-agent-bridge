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
    b.agent = mock_opencode
    b.bot_user_id = BOT_USER_ID
    b._busy = False
    b._goodbye_sent = False
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

    def test_posts_goodbye_only_once(self, greeting_bot, mock_driver) -> None:
        with patch("mm_agent_bridge.bot.socket.gethostname", return_value="host-1"):
            greeting_bot._send_goodbye()
            greeting_bot._send_goodbye()

        mock_driver.posts.create_post.assert_called_once_with(
            options={
                "channel_id": "ch-greet",
                "message": "Goodbye, shutting down! (host: host-1)",
            }
        )


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
    async def test_success_posts_reply_when_ack_creation_fails(
        self, bot, mock_driver, mock_opencode
    ) -> None:
        """When ack create_post fails, response is posted as a new reply."""
        mock_driver.posts.create_post.side_effect = [
            RuntimeError("ack failed"),
            {"id": "final-reply-id"},
        ]
        mock_opencode.chat.return_value = "Final answer."

        post = {
            "id": "p1",
            "channel_id": "ch-1",
            "user_id": "u1",
            "message": "@ai-agent question",
            "root_id": "",
        }
        await bot._process_post(post)

        assert mock_driver.posts.create_post.call_count == 2
        assert mock_driver.posts.patch_post.call_count == 0
        final_opts = mock_driver.posts.create_post.call_args_list[1].kwargs["options"]
        assert final_opts["root_id"] == "p1"
        assert "Final answer." in final_opts["message"]

    @pytest.mark.asyncio
    async def test_error_posts_reply_when_ack_creation_fails(
        self, bot, mock_driver, mock_opencode
    ) -> None:
        """When ack create_post fails and agent errors, error is posted as a new reply."""
        mock_driver.posts.create_post.side_effect = [
            RuntimeError("ack failed"),
            {"id": "error-reply-id"},
        ]
        mock_opencode.chat.side_effect = RuntimeError("boom")

        post = {
            "id": "p1",
            "channel_id": "ch-1",
            "user_id": "u1",
            "message": "@ai-agent fail",
            "root_id": "",
        }
        await bot._process_post(post)

        assert mock_driver.posts.create_post.call_count == 2
        assert mock_driver.posts.patch_post.call_count == 0
        final_opts = mock_driver.posts.create_post.call_args_list[1].kwargs["options"]
        assert final_opts["root_id"] == "p1"
        assert "error" in final_opts["message"].lower()
