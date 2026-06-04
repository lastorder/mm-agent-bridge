"""Unit tests for the queue consumer and _process_post logic."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mm_agent_bridge.bot import AgentBridge

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
        # Single positional arg is the cleaned text with sender prefix.
        assert call_args.args[0] == "@user-user-1: explain auth.py"

    @pytest.mark.asyncio
    async def test_replies_in_thread(self, bot, mock_driver, mock_opencode) -> None:
        post = _make_post(post_id="post-99")
        await bot._process_post(post)

        # Ack is posted in-thread via create_post.
        mock_driver.posts.create_post.assert_called_once()
        opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert opts["channel_id"] == "ch-1"
        assert opts["root_id"] == "post-99"
        assert opts["message"] == "@user-user-1 Processing your request..."

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
        assert patch_args.kwargs["options"]["message"] == "@user-user-1 The answer is 42."

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
        """When busy, queued notice is posted with @mention and 'queue' keyword."""
        bot._busy = True

        raw = make_posted_event(
            message="@ai-agent second request",
            mentions=[BOT_USER_ID],
            user_id="user-2",
        )
        await bot.handle_websocket_event(raw)

        mock_driver.posts.create_post.assert_called_once()
        opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert "queue" in opts["message"].lower()
        assert opts["message"].startswith("@user-user-2 ")

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

    @pytest.mark.asyncio
    async def test_notification_when_work_is_already_queued(self, bot, mock_driver) -> None:
        bot._busy = False
        await bot.queue.put({"id": "existing"})

        raw = make_posted_event(
            message="@ai-agent second request",
            mentions=[BOT_USER_ID],
            user_id="user-2",
        )
        await bot.handle_websocket_event(raw)

        mock_driver.posts.create_post.assert_called_once()
        opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert "queue" in opts["message"].lower()

    @pytest.mark.asyncio
    async def test_queued_notice_saves_ack_post_id(self, bot, mock_driver) -> None:
        """Queued notice post ID is saved as _ack_post_id on the enqueued post."""
        bot._busy = True
        mock_driver.posts.create_post.return_value = {"id": "queued-post-id"}

        raw = make_posted_event(
            message="@ai-agent request",
            mentions=[BOT_USER_ID],
            user_id="user-2",
        )
        await bot.handle_websocket_event(raw)

        post = bot.queue.get_nowait()
        assert post["_ack_post_id"] == "queued-post-id"

    @pytest.mark.asyncio
    async def test_queued_post_reused_as_ack(self, bot, mock_driver, mock_opencode) -> None:
        """When _ack_post_id exists, _process_post updates it instead of creating a new post."""
        mock_opencode.chat.return_value = "Done."
        post = {
            "id": "p1",
            "channel_id": "ch-1",
            "user_id": "user-1",
            "message": "@ai-agent work",
            "root_id": "",
            "_ack_post_id": "queued-post-id",
        }
        await bot._process_post(post)

        # No new post created — the queued notice post is reused.
        mock_driver.posts.create_post.assert_not_called()
        # Two patch_post calls: processing update + final answer.
        assert mock_driver.posts.patch_post.call_count == 2
        processing_opts = mock_driver.posts.patch_post.call_args_list[0].kwargs["options"]
        assert "Processing your request..." in processing_opts["message"]
        final_opts = mock_driver.posts.patch_post.call_args_list[1].kwargs["options"]
        assert "Done." in final_opts["message"]


class TestThreadContext:
    """Tests for thread context fetching and formatting in _process_post."""

    def _thread_response(self, posts: list[dict]) -> dict:
        posts_map = {p["id"]: p for p in posts}
        order = [p["id"] for p in reversed(posts)]
        return {"order": order, "posts": posts_map}

    @pytest.mark.asyncio
    async def test_thread_context_prepended_to_agent_text(
        self, bot, mock_driver, mock_opencode
    ) -> None:
        """When post is in a thread, context is prepended to agent.chat() input."""
        thread_posts = [
            {"id": "root-1", "user_id": "u1", "message": "Help me fix auth", "create_at": 1000},
            {"id": "p2", "user_id": "u2", "message": "Check auth.ts", "create_at": 2000},
        ]
        mock_driver.posts.get_thread.return_value = self._thread_response(thread_posts)

        post = _make_post(
            message="@ai-agent fix the bug",
            post_id="p3",
            root_id="root-1",
        )
        await bot._process_post(post)

        # Verify agent.chat was called with context prepended.
        call_text = mock_opencode.chat.call_args.args[0]
        assert "[Thread context]" in call_text
        assert "@user-u1: Help me fix auth" in call_text
        assert "@user-u2: Check auth.ts" in call_text
        assert "[Current request]" in call_text
        assert call_text.endswith("fix the bug")

    @pytest.mark.asyncio
    async def test_no_context_for_top_level_post(
        self, bot, mock_driver, mock_opencode
    ) -> None:
        """Top-level posts (no root_id) should NOT fetch thread context."""
        post = _make_post(message="@ai-agent hello", root_id="")
        await bot._process_post(post)

        mock_driver.posts.get_thread.assert_not_called()
        assert mock_opencode.chat.call_args.args[0] == "@user-user-1: hello"

    @pytest.mark.asyncio
    async def test_thread_context_excludes_triggering_post(
        self, bot, mock_driver, mock_opencode
    ) -> None:
        """The triggering post itself should be excluded from context."""
        thread_posts = [
            {"id": "root-1", "user_id": "u1", "message": "root msg", "create_at": 1000},
            {"id": "trigger-post", "user_id": "u2", "message": "@ai-agent do stuff", "create_at": 2000},
        ]
        mock_driver.posts.get_thread.return_value = self._thread_response(thread_posts)

        post = _make_post(
            message="@ai-agent do stuff",
            post_id="trigger-post",
            root_id="root-1",
        )
        await bot._process_post(post)

        call_text = mock_opencode.chat.call_args.args[0]
        assert "@user-u1: root msg" in call_text
        # The trigger post message should NOT appear in context.
        assert "@user-u2: @ai-agent do stuff" not in call_text

    @pytest.mark.asyncio
    async def test_empty_thread_context_does_not_prepend(
        self, bot, mock_driver, mock_opencode
    ) -> None:
        """If thread has no other messages, no context header is added."""
        # Thread only has the triggering post itself.
        thread_posts = [
            {"id": "trigger-post", "user_id": "u1", "message": "@ai-agent hi", "create_at": 1000},
        ]
        mock_driver.posts.get_thread.return_value = self._thread_response(thread_posts)

        post = _make_post(
            message="@ai-agent hi",
            post_id="trigger-post",
            root_id="root-1",
        )
        await bot._process_post(post)

        call_text = mock_opencode.chat.call_args.args[0]
        assert "[Thread context]" not in call_text
        assert call_text == "@user-user-1: hi"

    @pytest.mark.asyncio
    async def test_thread_fetch_failure_proceeds_without_context(
        self, bot, mock_driver, mock_opencode
    ) -> None:
        """If get_post_thread fails, processing continues without context."""
        mock_driver.posts.get_thread.side_effect = RuntimeError("API down")

        post = _make_post(
            message="@ai-agent hello",
            post_id="p2",
            root_id="root-1",
        )
        await bot._process_post(post)

        # Agent still called with sender-prefixed cleaned text.
        call_text = mock_opencode.chat.call_args.args[0]
        assert call_text == "@user-user-1: hello"

    @pytest.mark.asyncio
    async def test_thread_context_includes_bot_replies(
        self, bot, mock_driver, mock_opencode
    ) -> None:
        """Bot's own previous replies in the thread should be included."""
        thread_posts = [
            {"id": "root-1", "user_id": "u1", "message": "How does auth work?", "create_at": 1000},
            {"id": "p2", "user_id": BOT_USER_ID, "message": "Auth uses JWT tokens.", "create_at": 2000},
            {"id": "p3", "user_id": "u1", "message": "@ai-agent tell me more", "create_at": 3000},
        ]
        mock_driver.posts.get_thread.return_value = self._thread_response(thread_posts)

        post = _make_post(
            message="@ai-agent tell me more",
            post_id="p3",
            root_id="root-1",
        )
        await bot._process_post(post)

        call_text = mock_opencode.chat.call_args.args[0]
        assert "@user-u1: How does auth work?" in call_text
        assert f"@user-{BOT_USER_ID}: Auth uses JWT tokens." in call_text

    @pytest.mark.asyncio
    async def test_thread_context_respects_max_messages(
        self, bot, mock_driver, mock_opencode
    ) -> None:
        """Only the most recent N messages are included in context."""
        from dataclasses import replace

        # Override config to limit to 2 messages.
        bot.config = replace(bot.config, thread_context_max_messages=2)

        thread_posts = [
            {"id": f"p{i}", "user_id": "u1", "message": f"msg {i}", "create_at": i * 1000}
            for i in range(1, 6)  # 5 posts
        ]
        mock_driver.posts.get_thread.return_value = self._thread_response(thread_posts)

        post = _make_post(
            message="@ai-agent now",
            post_id="p6",
            root_id="p1",
        )
        await bot._process_post(post)

        call_text = mock_opencode.chat.call_args.args[0]
        # Should only include the 2 most recent (p4, p5).
        assert "msg 4" in call_text
        assert "msg 5" in call_text
        assert "msg 1" not in call_text
        assert "msg 2" not in call_text
        assert "msg 3" not in call_text

    @pytest.mark.asyncio
    async def test_username_lookup_failure_uses_user_id(
        self, bot, mock_driver, mock_opencode
    ) -> None:
        """When username lookup fails, user_id is used as fallback."""
        thread_posts = [
            {"id": "root-1", "user_id": "unknown-user", "message": "hi", "create_at": 1000},
        ]
        mock_driver.posts.get_thread.return_value = self._thread_response(thread_posts)

        # Make get_user raise for the unknown user.
        original_side_effect = mock_driver.users.get_user.side_effect

        def selective_get_user(uid):
            if uid == "unknown-user":
                raise RuntimeError("not found")
            return original_side_effect(uid)

        mock_driver.users.get_user.side_effect = selective_get_user

        post = _make_post(
            message="@ai-agent respond",
            post_id="p2",
            root_id="root-1",
        )
        await bot._process_post(post)

        call_text = mock_opencode.chat.call_args.args[0]
        # Falls back to user_id as username.
        assert "@unknown-user: hi" in call_text


class TestHostSuffix:
    """Tests for the msg_show_host feature appending host info to replies."""

    @pytest.fixture
    def host_bot(
        self, config, mock_driver: MagicMock, mock_opencode: AsyncMock
    ) -> AgentBridge:
        """AgentBridge with msg_show_host enabled."""
        cfg = replace(config, msg_show_host=True)
        b = AgentBridge.__new__(AgentBridge)
        b.config = cfg
        b.driver = mock_driver
        b.agent = mock_opencode
        b.bot_user_id = BOT_USER_ID
        b._busy = False
        b._goodbye_sent = False
        b.queue = asyncio.Queue()
        return b

    @pytest.mark.asyncio
    async def test_response_includes_host_suffix(
        self, host_bot, mock_driver, mock_opencode
    ) -> None:
        mock_opencode.chat.return_value = "The answer is 42."
        post = _make_post()
        with patch("mm_agent_bridge.bot.socket.gethostname", return_value="srv-1"):
            await host_bot._process_post(post)

        patch_args = mock_driver.posts.patch_post.call_args
        msg = patch_args.kwargs["options"]["message"]
        assert "The answer is 42." in msg
        assert msg.endswith("\n(host: srv-1)")

    @pytest.mark.asyncio
    async def test_ack_includes_host_suffix(
        self, host_bot, mock_driver, mock_opencode
    ) -> None:
        post = _make_post()
        with patch("mm_agent_bridge.bot.socket.gethostname", return_value="srv-1"):
            await host_bot._process_post(post)

        ack_opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert ack_opts["message"].endswith("\n(host: srv-1)")

    @pytest.mark.asyncio
    async def test_no_host_suffix_when_disabled(
        self, bot, mock_driver, mock_opencode
    ) -> None:
        """Default config has msg_show_host=False — no suffix."""
        mock_opencode.chat.return_value = "The answer."
        post = _make_post()
        await bot._process_post(post)

        patch_args = mock_driver.posts.patch_post.call_args
        msg = patch_args.kwargs["options"]["message"]
        assert "(host:" not in msg

    @pytest.mark.asyncio
    async def test_error_includes_host_suffix(
        self, host_bot, mock_driver, mock_opencode
    ) -> None:
        mock_opencode.chat.side_effect = RuntimeError("boom")
        post = _make_post()
        with patch("mm_agent_bridge.bot.socket.gethostname", return_value="srv-1"):
            await host_bot._process_post(post)

        patch_args = mock_driver.posts.patch_post.call_args
        msg = patch_args.kwargs["options"]["message"]
        assert "error" in msg.lower()
        assert msg.endswith("\n(host: srv-1)")


class TestQueueFull:
    """Tests that queue-full rejection works correctly."""

    @pytest.fixture
    def small_queue_bot(
        self, mock_driver: MagicMock, mock_opencode: AsyncMock
    ) -> AgentBridge:
        """Bot with queue_max_size=2 for easy testing."""
        from mm_agent_bridge.config import Config

        cfg = Config(
            mm_url="localhost",
            mm_token="test-token",
            agent_type="opencode",
            opencode_model_id="test-model",
            opencode_provider_id="test-provider",
            queue_max_size=2,
        )
        b = AgentBridge.__new__(AgentBridge)
        b.config = cfg
        b.driver = mock_driver
        b.agent = mock_opencode
        b.bot_user_id = BOT_USER_ID
        b._busy = False
        b._goodbye_sent = False

        import asyncio

        b.queue = asyncio.Queue(maxsize=cfg.queue_max_size)
        return b

    @pytest.mark.asyncio
    async def test_rejects_when_queue_full(
        self, small_queue_bot, mock_driver
    ) -> None:
        """When queue is full, new requests are rejected (not enqueued)."""
        bot = small_queue_bot
        # Fill queue to capacity.
        await bot.queue.put({"id": "fill-1"})
        await bot.queue.put({"id": "fill-2"})
        assert bot.queue.full()

        raw = make_posted_event(
            message="@ai-agent new request",
            mentions=[BOT_USER_ID],
            user_id="user-3",
        )
        await bot.handle_websocket_event(raw)

        # Should NOT have been enqueued.
        assert bot.queue.qsize() == 2

        # Should have posted a rejection reply.
        mock_driver.posts.create_post.assert_called_once()
        opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert "busy" in opts["message"].lower() or "later" in opts["message"].lower()

    @pytest.mark.asyncio
    async def test_rejection_includes_mention(
        self, small_queue_bot, mock_driver
    ) -> None:
        """Rejection message includes @mention prefix."""
        bot = small_queue_bot
        await bot.queue.put({"id": "fill-1"})
        await bot.queue.put({"id": "fill-2"})

        raw = make_posted_event(
            message="@ai-agent test",
            mentions=[BOT_USER_ID],
            user_id="user-7",
        )
        await bot.handle_websocket_event(raw)

        opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert opts["message"].startswith("@user-user-7 ")

    @pytest.mark.asyncio
    async def test_enqueues_when_not_full(
        self, small_queue_bot, mock_driver
    ) -> None:
        """When queue is not full, request is enqueued normally."""
        bot = small_queue_bot
        # Put only 1 item (capacity is 2).
        await bot.queue.put({"id": "fill-1"})
        assert not bot.queue.full()

        raw = make_posted_event(
            message="@ai-agent hello",
            mentions=[BOT_USER_ID],
            user_id="user-4",
        )
        await bot.handle_websocket_event(raw)

        # Should have been enqueued (now 2 items).
        assert bot.queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_custom_queue_full_message(
        self, mock_driver, mock_opencode
    ) -> None:
        """Custom MSG_QUEUE_FULL text is used in rejection reply."""
        from mm_agent_bridge.config import Config

        cfg = Config(
            mm_url="localhost",
            mm_token="test-token",
            agent_type="opencode",
            opencode_model_id="test-model",
            opencode_provider_id="test-provider",
            queue_max_size=1,
            msg_queue_full="Custom busy message!",
        )
        b = AgentBridge.__new__(AgentBridge)
        b.config = cfg
        b.driver = mock_driver
        b.agent = mock_opencode
        b.bot_user_id = BOT_USER_ID
        b._busy = False
        b._goodbye_sent = False

        import asyncio

        b.queue = asyncio.Queue(maxsize=1)
        await b.queue.put({"id": "fill-1"})

        raw = make_posted_event(
            message="@ai-agent test",
            mentions=[BOT_USER_ID],
            user_id="user-5",
        )
        await b.handle_websocket_event(raw)

        opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert "Custom busy message!" in opts["message"]
