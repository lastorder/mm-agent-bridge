"""Integration tests: MM websocket events flowing into the queue."""

from __future__ import annotations

import pytest

from tests.conftest import BOT_USER_ID, make_posted_event, make_non_posted_event


class TestMmToQueue:
    """Verify that websocket events are correctly filtered and enqueued."""

    @pytest.mark.asyncio
    async def test_rapid_fire_messages(self, bot, mock_driver) -> None:
        """5 quick mentions arrive; all 5 enqueued, 4 get queued notice."""
        # First message: bot is idle -> no notification.
        raw_first = make_posted_event(
            message="@ai-agent first",
            post_id="p1",
            mentions=[BOT_USER_ID],
            user_id="u1",
        )
        await bot.handle_websocket_event(raw_first)
        assert bot.queue.qsize() == 1
        mock_driver.posts.create_post.assert_not_called()

        # Simulate the bot becoming busy (as if the consumer picked it up).
        bot._busy = True

        # Next 4 messages: bot is busy -> each gets a notification.
        for i in range(2, 6):
            raw = make_posted_event(
                message=f"@ai-agent msg {i}",
                post_id=f"p{i}",
                mentions=[BOT_USER_ID],
                user_id=f"u{i}",
            )
            await bot.handle_websocket_event(raw)

        assert bot.queue.qsize() == 5
        # 4 queued notifications.
        assert mock_driver.posts.create_post.call_count == 4

    @pytest.mark.asyncio
    async def test_mixed_events_only_mentions_queued(self, bot) -> None:
        """A mix of typing, non-mention posts, and mentions -> only mentions enqueued."""
        events = [
            make_non_posted_event("typing"),
            make_posted_event(message="just chatting", user_id="u1"),
            make_posted_event(
                message="@ai-agent do X",
                mentions=[BOT_USER_ID],
                user_id="u2",
                post_id="p-mention-1",
            ),
            make_non_posted_event("channel_viewed"),
            make_posted_event(message="random stuff", user_id="u3"),
            make_posted_event(
                message="hey @ai-agent help",
                mentions=[BOT_USER_ID],
                user_id="u4",
                post_id="p-mention-2",
            ),
        ]

        for ev in events:
            await bot.handle_websocket_event(ev)

        assert bot.queue.qsize() == 2
        first = bot.queue.get_nowait()
        second = bot.queue.get_nowait()
        assert first["id"] == "p-mention-1"
        assert second["id"] == "p-mention-2"

    @pytest.mark.asyncio
    async def test_self_messages_never_enqueued(self, bot) -> None:
        """Bot's own messages are always ignored."""
        for _ in range(3):
            raw = make_posted_event(
                message="@ai-agent echo",
                user_id=BOT_USER_ID,
                mentions=[BOT_USER_ID],
            )
            await bot.handle_websocket_event(raw)

        assert bot.queue.empty()
