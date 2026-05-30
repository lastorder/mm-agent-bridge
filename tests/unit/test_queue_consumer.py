"""Unit tests for the queue consumer and _process_post logic."""

from __future__ import annotations

import pytest

from tests.conftest import BOT_USER_ID, make_posted_event


def _make_post(
    message: str = "@ai-agent hello",
    channel_id: str = "ch-1",
    post_id: str = "post-1",
    root_id: str = "",
) -> dict:
    return {
        "id": post_id,
        "channel_id": channel_id,
        "user_id": "user-1",
        "message": message,
        "root_id": root_id,
    }


class TestProcessPost:
    """Tests for AgentBridge._process_post()."""

    @pytest.mark.asyncio
    async def test_sends_cleaned_text_to_opencode(self, bot, mock_opencode) -> None:
        post = _make_post(message="@ai-agent explain auth.py")
        await bot._process_post(post)

        mock_opencode.chat.assert_awaited_once()
        call_args = mock_opencode.chat.call_args
        # Single positional arg is the cleaned text.
        assert call_args.args[0] == "explain auth.py"

    @pytest.mark.asyncio
    async def test_replies_in_thread(self, bot, mock_driver, mock_opencode) -> None:
        post = _make_post(post_id="post-99")
        await bot._process_post(post)

        # Ack is posted in-thread via create_post.
        mock_driver.posts.create_post.assert_called_once()
        opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert opts["channel_id"] == "ch-1"
        assert opts["root_id"] == "post-99"
        assert opts["message"] == "Processing your request..."

    @pytest.mark.asyncio
    async def test_uses_existing_root_id(self, bot, mock_driver, mock_opencode) -> None:
        """When the post is already in a thread, use its root_id."""
        post = _make_post(post_id="post-child", root_id="post-root")
        await bot._process_post(post)

        opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert opts["root_id"] == "post-root"

    @pytest.mark.asyncio
    async def test_response_text_posted(self, bot, mock_driver, mock_opencode) -> None:
        mock_opencode.chat.return_value = "The answer is 42."
        post = _make_post()
        await bot._process_post(post)

        # Ack is posted via create_post, then response updates via patch_post.
        mock_driver.posts.patch_post.assert_called_once()
        patch_args = mock_driver.posts.patch_post.call_args
        assert patch_args.kwargs["options"]["message"] == "The answer is 42."

    @pytest.mark.asyncio
    async def test_error_posts_error_message(self, bot, mock_driver, mock_opencode) -> None:
        mock_opencode.chat.side_effect = RuntimeError("boom")
        post = _make_post()
        await bot._process_post(post)

        # Error updates the ack post via patch_post.
        mock_driver.posts.patch_post.assert_called_once()
        patch_args = mock_driver.posts.patch_post.call_args
        assert "error" in patch_args.kwargs["options"]["message"].lower()

    @pytest.mark.asyncio
    async def test_error_does_not_block_queue(self, bot, mock_driver, mock_opencode) -> None:
        """After an error the bot should reset busy and keep processing."""
        mock_opencode.chat.side_effect = RuntimeError("fail")
        post = _make_post()
        await bot._process_post(post)

        assert bot._busy is False

    @pytest.mark.asyncio
    async def test_empty_message_after_clean(self, bot, mock_driver, mock_opencode) -> None:
        post = _make_post(message="@ai-agent")
        await bot._process_post(post)

        # Should NOT call opencode.
        mock_opencode.chat.assert_not_awaited()
        # Should reply with a notice.
        opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert "empty" in opts["message"].lower()

    @pytest.mark.asyncio
    async def test_busy_flag_during_processing(self, bot, mock_opencode) -> None:
        """busy should be True while processing and False after."""
        busy_during: list[bool] = []

        original_chat = mock_opencode.chat

        async def spy_chat(*args, **kwargs):
            busy_during.append(bot._busy)
            return await original_chat(*args, **kwargs)

        mock_opencode.chat = spy_chat

        post = _make_post()
        await bot._process_post(post)

        assert busy_during == [True]
        assert bot._busy is False


class TestQueuedNotification:
    """Tests that a 'queued' message is posted when the bot is busy."""

    @pytest.mark.asyncio
    async def test_queued_notification_when_busy(self, bot, mock_driver) -> None:
        bot._busy = True

        raw = make_posted_event(
            message="@ai-agent second request",
            mentions=[BOT_USER_ID],
            user_id="user-2",
        )
        await bot.handle_websocket_event(raw)

        # Should have posted a queued notification.
        mock_driver.posts.create_post.assert_called_once()
        opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert "queue" in opts["message"].lower()

    @pytest.mark.asyncio
    async def test_no_notification_when_idle(self, bot, mock_driver) -> None:
        bot._busy = False

        raw = make_posted_event(
            message="@ai-agent first request",
            mentions=[BOT_USER_ID],
            user_id="user-2",
        )
        await bot.handle_websocket_event(raw)

        # No notification should be posted — only enqueued.
        mock_driver.posts.create_post.assert_not_called()
