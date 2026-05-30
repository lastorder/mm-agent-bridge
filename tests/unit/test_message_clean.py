"""Unit tests for mention text cleaning."""

from __future__ import annotations

import pytest

from mm_agent_bridge.mm import clean_mention

MENTION = "ai-agent"


class TestCleanMention:

    def test_strip_prefix_mention(self) -> None:
        assert clean_mention("@ai-agent do something", MENTION) == "do something"

    def test_strip_middle_mention(self) -> None:
        assert clean_mention("hey @ai-agent do X", MENTION) == "hey do X"

    def test_strip_multiple_mentions(self) -> None:
        result = clean_mention("@ai-agent hello @ai-agent world", MENTION)
        assert result == "hello world"

    def test_case_insensitive(self) -> None:
        assert clean_mention("@ai-agent help", MENTION) == "help"

    def test_preserve_other_mentions(self) -> None:
        result = clean_mention("@ai-agent tell @alice about it", MENTION)
        assert result == "tell @alice about it"

    def test_empty_after_strip(self) -> None:
        assert clean_mention("@ai-agent", MENTION) == ""

    def test_whitespace_after_strip(self) -> None:
        assert clean_mention("  @ai-agent   ", MENTION) == ""

    def test_no_mention_unchanged(self) -> None:
        assert clean_mention("just plain text", MENTION) == "just plain text"

    def test_mention_with_newline(self) -> None:
        result = clean_mention("@ai-agent\nplease help", MENTION)
        assert result == "please help"
