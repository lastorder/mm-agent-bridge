"""Unit tests for mm.py helper functions: post_message, update_post_message, post_reply."""

from __future__ import annotations

from unittest.mock import MagicMock

from mm_agent_bridge.mm import post_message, post_reply, update_post_message


class TestPostReply:
    """Tests for post_reply() return value."""

    def test_returns_post_id(self) -> None:
        driver = MagicMock()
        driver.posts.create_post.return_value = {"id": "new-post-123"}

        result = post_reply(driver, "ch-1", "root-1", "hello")

        assert result == "new-post-123"
        driver.posts.create_post.assert_called_once_with(
            options={
                "channel_id": "ch-1",
                "message": "hello",
                "root_id": "root-1",
            }
        )

    def test_returns_empty_string_on_exception(self) -> None:
        driver = MagicMock()
        driver.posts.create_post.side_effect = RuntimeError("network error")

        result = post_reply(driver, "ch-1", "root-1", "hello")

        assert result == ""


class TestPostMessage:
    """Tests for post_message() (top-level, no root_id)."""

    def test_posts_without_root_id(self) -> None:
        driver = MagicMock()
        driver.posts.create_post.return_value = {"id": "msg-456"}

        result = post_message(driver, "ch-greeting", "Agent online!")

        assert result == "msg-456"
        driver.posts.create_post.assert_called_once_with(
            options={
                "channel_id": "ch-greeting",
                "message": "Agent online!",
            }
        )

    def test_returns_empty_string_on_exception(self) -> None:
        driver = MagicMock()
        driver.posts.create_post.side_effect = RuntimeError("fail")

        result = post_message(driver, "ch-1", "hello")

        assert result == ""


class TestUpdatePostMessage:
    """Tests for update_post_message()."""

    def test_calls_patch_post(self) -> None:
        driver = MagicMock()

        update_post_message(driver, "post-123", "Updated content")

        driver.posts.patch_post.assert_called_once_with(
            "post-123", options={"message": "Updated content"}
        )

    def test_skips_when_post_id_empty(self) -> None:
        driver = MagicMock()

        update_post_message(driver, "", "should not be sent")

        driver.posts.patch_post.assert_not_called()

    def test_handles_exception_gracefully(self) -> None:
        driver = MagicMock()
        driver.posts.patch_post.side_effect = RuntimeError("fail")

        # Should not raise.
        update_post_message(driver, "post-123", "content")
