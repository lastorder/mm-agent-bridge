"""Unit tests for mm.py helper functions: post_message, update_post_message, post_reply, get_thread_messages."""

from __future__ import annotations

from unittest.mock import MagicMock

from mm_agent_bridge.mm import get_thread_messages, post_message, post_reply, update_post_message


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


class TestGetThreadMessages:
    """Tests for get_thread_messages()."""

    def _make_thread_response(self, posts: list[dict]) -> dict:
        """Build a mock get_post_thread API response."""
        posts_map = {p["id"]: p for p in posts}
        # API returns order newest-first.
        order = [p["id"] for p in reversed(posts)]
        return {"order": order, "posts": posts_map}

    def _make_post(
        self, post_id: str, user_id: str, message: str, create_at: int
    ) -> dict:
        return {
            "id": post_id,
            "user_id": user_id,
            "message": message,
            "create_at": create_at,
        }

    def test_returns_posts_sorted_by_create_at(self) -> None:
        posts = [
            self._make_post("p1", "u1", "first", 1000),
            self._make_post("p2", "u2", "second", 2000),
            self._make_post("p3", "u1", "third", 3000),
        ]
        driver = MagicMock()
        driver.posts.get_thread.return_value = self._make_thread_response(posts)

        result = get_thread_messages(driver, "p1")

        assert len(result) == 3
        assert result[0]["id"] == "p1"
        assert result[1]["id"] == "p2"
        assert result[2]["id"] == "p3"

    def test_excludes_specified_post(self) -> None:
        posts = [
            self._make_post("p1", "u1", "root", 1000),
            self._make_post("p2", "u2", "reply", 2000),
            self._make_post("p3", "u1", "trigger", 3000),
        ]
        driver = MagicMock()
        driver.posts.get_thread.return_value = self._make_thread_response(posts)

        result = get_thread_messages(driver, "p1", exclude_post_id="p3")

        assert len(result) == 2
        assert all(p["id"] != "p3" for p in result)

    def test_limits_to_max_messages(self) -> None:
        posts = [
            self._make_post(f"p{i}", "u1", f"msg {i}", i * 1000)
            for i in range(1, 11)  # 10 posts
        ]
        driver = MagicMock()
        driver.posts.get_thread.return_value = self._make_thread_response(posts)

        result = get_thread_messages(driver, "p1", max_messages=3)

        assert len(result) == 3
        # Should be the 3 most recent.
        assert result[0]["id"] == "p8"
        assert result[1]["id"] == "p9"
        assert result[2]["id"] == "p10"

    def test_returns_empty_on_api_failure(self) -> None:
        driver = MagicMock()
        driver.posts.get_thread.side_effect = RuntimeError("network error")

        result = get_thread_messages(driver, "p1")

        assert result == []

    def test_returns_empty_for_empty_root_id(self) -> None:
        driver = MagicMock()

        result = get_thread_messages(driver, "")

        assert result == []
        driver.posts.get_thread.assert_not_called()

    def test_handles_missing_posts_in_order(self) -> None:
        """If order contains IDs not in posts map, they are skipped."""
        posts = [self._make_post("p1", "u1", "only one", 1000)]
        thread_response = {
            "order": ["p1", "p-missing"],
            "posts": {"p1": posts[0]},
        }
        driver = MagicMock()
        driver.posts.get_thread.return_value = thread_response

        result = get_thread_messages(driver, "p1")

        assert len(result) == 1
        assert result[0]["id"] == "p1"
