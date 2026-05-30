"""Unit tests for Mattermost event filtering logic."""

from __future__ import annotations

import json

import pytest

from mm_agent_bridge.mm import is_mention_for_bot, parse_posted_event
from tests.conftest import BOT_USER_ID, make_non_posted_event, make_posted_event

MENTION = "ai-agent"


class TestParsePostedEvent:
    """Tests for parse_posted_event()."""

    def test_valid_posted_event(self) -> None:
        raw = make_posted_event(message="hello world", post_id="p1")
        post = parse_posted_event(raw)
        assert post is not None
        assert post["id"] == "p1"
        assert post["message"] == "hello world"

    def test_non_posted_event_returns_none(self) -> None:
        raw = make_non_posted_event("typing")
        assert parse_posted_event(raw) is None

    def test_invalid_json_returns_none(self) -> None:
        assert parse_posted_event("not-json{{{") is None

    def test_mentions_parsed(self) -> None:
        raw = make_posted_event(
            message="@ai-agent hi",
            mentions=["user-a", "user-b"],
        )
        post = parse_posted_event(raw)
        assert post is not None
        assert post["_mentions"] == ["user-a", "user-b"]

    def test_missing_mentions_defaults_to_empty(self) -> None:
        raw = make_posted_event(message="hello")
        post = parse_posted_event(raw)
        assert post is not None
        assert post["_mentions"] == []

    def test_malformed_post_json_returns_none(self) -> None:
        """If ``data.post`` is not valid JSON the event is skipped."""
        raw = json.dumps({"event": "posted", "data": {"post": "{{bad"}})
        assert parse_posted_event(raw) is None


class TestIsMentionForBot:
    """Tests for is_mention_for_bot()."""

    def test_mention_in_mentions_list(self) -> None:
        post = {"_mentions": [BOT_USER_ID], "message": "hey"}
        assert is_mention_for_bot(post, BOT_USER_ID, MENTION) is True

    def test_no_mention_returns_false(self) -> None:
        post = {"_mentions": [], "message": "hey someone"}
        assert is_mention_for_bot(post, BOT_USER_ID, MENTION) is False

    def test_fallback_to_text_match(self) -> None:
        """When ``_mentions`` is absent or empty, check the text."""
        post = {"_mentions": [], "message": "hey @ai-agent do stuff"}
        assert is_mention_for_bot(post, BOT_USER_ID, MENTION) is True

    def test_case_insensitive_text_match(self) -> None:
        post = {"_mentions": [], "message": "@ai-agent help"}
        assert is_mention_for_bot(post, BOT_USER_ID, MENTION) is True

    def test_partial_word_no_match(self) -> None:
        """``@ai-agents`` (extra 's') should not match."""
        post = {"_mentions": [], "message": "cc @ai-agents"}
        assert is_mention_for_bot(post, BOT_USER_ID, MENTION) is False

    def test_different_user_in_mentions(self) -> None:
        post = {"_mentions": ["other-user-id"], "message": "hello"}
        assert is_mention_for_bot(post, BOT_USER_ID, MENTION) is False


class TestHandleWebsocketEvent:
    """Integration-light tests: full event_handler with the bot fixture."""

    @pytest.mark.asyncio
    async def test_ignore_non_posted(self, bot) -> None:
        raw = make_non_posted_event("typing")
        await bot.handle_websocket_event(raw)
        assert bot.queue.empty()

    @pytest.mark.asyncio
    async def test_ignore_self_message(self, bot) -> None:
        """Bot's own messages are ignored to prevent loops."""
        raw = make_posted_event(
            message="@ai-agent hello",
            user_id=BOT_USER_ID,
            mentions=[BOT_USER_ID],
        )
        await bot.handle_websocket_event(raw)
        assert bot.queue.empty()

    @pytest.mark.asyncio
    async def test_enqueue_valid_mention(self, bot) -> None:
        raw = make_posted_event(
            message="@ai-agent help me",
            mentions=[BOT_USER_ID],
            user_id="someone-else",
        )
        await bot.handle_websocket_event(raw)
        assert bot.queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_ignore_message_without_mention(self, bot) -> None:
        raw = make_posted_event(
            message="just chatting",
            user_id="someone",
        )
        await bot.handle_websocket_event(raw)
        assert bot.queue.empty()
