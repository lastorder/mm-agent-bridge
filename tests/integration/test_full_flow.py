"""Integration tests: full end-to-end flow from MM event to MM reply."""

from __future__ import annotations

import pytest

from tests.conftest import BOT_USER_ID, make_posted_event


class TestFullFlow:
    """End-to-end: MM websocket event -> queue -> OpenCode -> MM reply."""

    @pytest.mark.asyncio
    async def test_mention_to_reply(self, bot, mock_driver, mock_opencode) -> None:
        """Single mention flows through the entire pipeline."""
        mock_opencode.chat.return_value = "Here is the explanation."

        # 1. Simulate websocket event.
        raw = make_posted_event(
            message="@ai-agent explain auth.py",
            channel_id="ch-abc",
            post_id="post-100",
            user_id="user-x",
            mentions=[BOT_USER_ID],
        )
        await bot.handle_websocket_event(raw)

        # 2. Process via queue consumer.
        post = bot.queue.get_nowait()
        await bot._process_post(post)

        # 3. Verify the ack was posted in-thread.
        mock_driver.posts.create_post.assert_called_once()
        ack_opts = mock_driver.posts.create_post.call_args.kwargs["options"]
        assert ack_opts["channel_id"] == "ch-abc"
        assert ack_opts["root_id"] == "post-100"
        assert ack_opts["message"] == "@user-user-x Processing your request..."

        # 4. Verify the response updated the ack post.
        mock_driver.posts.patch_post.assert_called_once()
        patch_args = mock_driver.posts.patch_post.call_args
        assert patch_args.kwargs["options"]["message"] == "@user-user-x Here is the explanation."

    @pytest.mark.asyncio
    async def test_sequential_processing(self, bot, mock_driver, mock_opencode) -> None:
        """Three concurrent messages are processed in FIFO order."""
        responses = [
            "Answer to first",
            "Answer to second",
            "Answer to third",
        ]
        call_count = 0

        async def chat_side_effect(*args, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            return responses[idx]

        mock_opencode.chat.side_effect = chat_side_effect

        # Enqueue 3 messages.
        for i in range(3):
            raw = make_posted_event(
                message=f"@ai-agent question {i}",
                post_id=f"post-{i}",
                channel_id="ch-1",
                user_id="user-1",
                mentions=[BOT_USER_ID],
            )
            await bot.handle_websocket_event(raw)

        assert bot.queue.qsize() == 3

        # Process them sequentially.
        for _ in range(3):
            post = bot.queue.get_nowait()
            await bot._process_post(post)

        assert bot.queue.empty()
        create_calls = mock_driver.posts.create_post.call_args_list
        ack_calls = [
            call
            for call in create_calls
            if "processing" in call.kwargs["options"]["message"].lower()
        ]
        queued_calls = [
            call
            for call in create_calls
            if "queue" in call.kwargs["options"]["message"].lower()
        ]

        # Only the first (non-queued) message creates a new ack post;
        # the other two reuse the queued-notice post via patch_post.
        assert len(ack_calls) == 1
        assert len(queued_calls) == 2
        # 5 patch_post calls: 1 answer + 2*(processing update + answer).
        assert mock_driver.posts.patch_post.call_count == 5

        # Verify responses in order — filter out "Processing your request..." updates.
        patch_calls = mock_driver.posts.patch_post.call_args_list
        response_patches = [
            c for c in patch_calls
            if "Processing your request..." not in c.kwargs["options"]["message"]
        ]
        assert len(response_patches) == 3
        for i, resp in enumerate(responses):
            opts = response_patches[i].kwargs["options"]
            assert resp in opts["message"]

    @pytest.mark.asyncio
    async def test_error_recovery(self, bot, mock_driver, mock_opencode) -> None:
        """Second message errors; first and third still get correct replies."""
        call_idx = 0

        async def chat_side_effect(*args, **kwargs):
            nonlocal call_idx
            idx = call_idx
            call_idx += 1
            if idx == 1:
                raise RuntimeError("simulated failure")
            return f"reply-{idx}"

        mock_opencode.chat.side_effect = chat_side_effect

        # Enqueue 3 messages.
        for i in range(3):
            raw = make_posted_event(
                message=f"@ai-agent task {i}",
                post_id=f"post-{i}",
                channel_id="ch-1",
                user_id="user-1",
                mentions=[BOT_USER_ID],
            )
            await bot.handle_websocket_event(raw)

        # Process all 3.
        for _ in range(3):
            post = bot.queue.get_nowait()
            await bot._process_post(post)

        create_calls = mock_driver.posts.create_post.call_args_list
        ack_calls = [
            call
            for call in create_calls
            if "processing" in call.kwargs["options"]["message"].lower()
        ]
        queued_calls = [
            call
            for call in create_calls
            if "queue" in call.kwargs["options"]["message"].lower()
        ]

        assert len(ack_calls) == 1
        assert len(queued_calls) == 2
        # 5 patch_post calls: 1 answer + 2*(processing update + answer/error).
        assert mock_driver.posts.patch_post.call_count == 5
        patch_calls = mock_driver.posts.patch_post.call_args_list

        # Filter out "Processing your request..." updates to get only response/error patches.
        response_patches = [
            c for c in patch_calls
            if "Processing your request..." not in c.kwargs["options"]["message"]
        ]
        assert len(response_patches) == 3

        # First: normal reply.
        assert "reply-0" in response_patches[0].kwargs["options"]["message"]
        # Second: error reply.
        assert "error" in response_patches[1].kwargs["options"]["message"].lower()
        # Third: normal reply (recovery).
        assert "reply-2" in response_patches[2].kwargs["options"]["message"]
        # Busy should be reset.
        assert bot._busy is False
