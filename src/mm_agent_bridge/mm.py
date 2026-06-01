"""Mattermost integration helpers.

Pure functions for parsing websocket events, detecting bot mentions,
cleaning mention text, and posting replies.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from mattermostdriver import Driver

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mention handling
# ---------------------------------------------------------------------------


def clean_mention(text: str, mention_name: str) -> str:
    """Remove all ``@<mention_name>`` occurrences from *text* and strip."""
    pattern = re.compile(rf"@{re.escape(mention_name)}\s*", re.IGNORECASE)
    cleaned = pattern.sub("", text).strip()
    logger.info("clean_mention: %r -> %r", text, cleaned)
    return cleaned


# ---------------------------------------------------------------------------
# Websocket event parsing
# ---------------------------------------------------------------------------


def parse_posted_event(raw: str) -> dict[str, Any] | None:
    """Parse a raw websocket message and return the inner post dict.

    Returns ``None`` when the event is not a ``posted`` event or the
    payload cannot be parsed.
    """
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        logger.info("parse_posted_event: received non-JSON payload, ignoring")
        return None

    event_type = msg.get("event", "<no event field>")

    if event_type != "posted":
        # Only log non-trivial events to avoid flooding with status/typing.
        if event_type not in ("typing", "status_change", "channel_viewed"):
            logger.info("parse_posted_event: event_type=%s, skipping", event_type)
        return None

    data = msg.get("data", {})
    try:
        post = json.loads(data.get("post", "{}"))
    except json.JSONDecodeError:
        logger.info("parse_posted_event: failed to parse data.post JSON")
        return None

    # Attach top-level mentions list for convenience.
    raw_mentions = data.get("mentions", "[]")
    try:
        post["_mentions"] = json.loads(raw_mentions)
    except json.JSONDecodeError:
        post["_mentions"] = []

    logger.info(
        "parse_posted_event: posted event received — post_id=%s, user_id=%s, "
        "channel_id=%s, message=%r, mentions=%s",
        post.get("id"),
        post.get("user_id"),
        post.get("channel_id"),
        post.get("message", "")[:100],
        post.get("_mentions"),
    )
    return post


def is_mention_for_bot(
    post: dict[str, Any], bot_user_id: str, mention_name: str
) -> bool:
    """Return ``True`` if *post* is an @mention directed at the bot."""
    mentions_list = post.get("_mentions", [])
    message = post.get("message", "")

    # Primary check: the server-parsed mentions list.
    if bot_user_id in mentions_list:
        logger.info(
            "is_mention_for_bot: MATCH via mentions list (bot_user_id=%s in %s)",
            bot_user_id,
            mentions_list,
        )
        return True

    # Fallback: text-based matching.
    pattern = rf"@{re.escape(mention_name)}\b"
    text_match = bool(re.search(pattern, message, re.IGNORECASE))
    if text_match:
        logger.info(
            "is_mention_for_bot: MATCH via text pattern in message=%r",
            message[:100],
        )
    else:
        logger.info(
            "is_mention_for_bot: NO MATCH — bot_user_id=%s not in mentions=%s, "
            "text pattern not found in message=%r",
            bot_user_id,
            mentions_list,
            message[:100],
        )
    return text_match


# ---------------------------------------------------------------------------
# Posting replies
# ---------------------------------------------------------------------------


def post_reply(
    driver: Driver, channel_id: str, root_id: str, message: str
) -> str:
    """Post an in-thread reply to Mattermost. Returns the new post ID."""
    logger.info(
        "post_reply: channel_id=%s, root_id=%s, message_length=%d",
        channel_id,
        root_id,
        len(message),
    )
    try:
        resp = driver.posts.create_post(
            options={
                "channel_id": channel_id,
                "message": message,
                "root_id": root_id,
            }
        )
        logger.info("post_reply: successfully posted reply, post_id=%s", resp.get("id"))
        return resp["id"]
    except Exception:
        logger.exception("post_reply: FAILED to post reply to channel %s", channel_id)
        return ""


def post_message(driver: Driver, channel_id: str, message: str) -> str:
    """Post a top-level message to a channel. Returns the new post ID."""
    logger.info(
        "post_message: channel_id=%s, message_length=%d",
        channel_id,
        len(message),
    )
    try:
        resp = driver.posts.create_post(
            options={
                "channel_id": channel_id,
                "message": message,
            }
        )
        logger.info("post_message: successfully posted, post_id=%s", resp.get("id"))
        return resp["id"]
    except Exception:
        logger.exception("post_message: FAILED to post to channel %s", channel_id)
        return ""


def update_post_message(driver: Driver, post_id: str, message: str) -> None:
    """Update an existing post's message text."""
    if not post_id:
        logger.warning("update_post_message: empty post_id, skipping update")
        return
    logger.info(
        "update_post_message: post_id=%s, new_message_length=%d",
        post_id,
        len(message),
    )
    try:
        driver.posts.patch_post(post_id, options={"message": message})
        logger.info("update_post_message: successfully updated post_id=%s", post_id)
    except Exception:
        logger.exception(
            "update_post_message: FAILED to update post %s", post_id
        )


def post_or_update_reply(
    driver: Driver, channel_id: str, root_id: str, post_id: str, message: str
) -> str:
    """Update an ack post when possible, otherwise post a new thread reply.

    Returns the post ID that now contains the message, or ``""`` if both
    operations fail.
    """
    if post_id:
        update_post_message(driver, post_id, message)
        return post_id
    return post_reply(driver, channel_id, root_id, message)


# ---------------------------------------------------------------------------
# Thread context
# ---------------------------------------------------------------------------


def get_thread_messages(
    driver: Driver,
    root_id: str,
    *,
    exclude_post_id: str = "",
    max_messages: int = 20,
) -> list[dict[str, Any]]:
    """Fetch messages in a thread, sorted by creation time (ascending).

    Args:
        driver: Mattermost driver instance.
        root_id: The root post ID of the thread.
        exclude_post_id: A post ID to exclude (typically the triggering post).
        max_messages: Maximum number of messages to return (most recent N).

    Returns:
        A list of post dicts, each containing at least ``user_id`` and
        ``message``.  Returns an empty list on API failure.
    """
    if not root_id:
        return []

    try:
        thread_data = driver.posts.get_thread(root_id)
    except Exception:
        logger.warning(
            "get_thread_messages: failed to fetch thread for root_id=%s",
            root_id,
            exc_info=True,
        )
        return []

    posts_map: dict[str, Any] = thread_data.get("posts", {})
    order: list[str] = thread_data.get("order", [])

    # Build list sorted by create_at (ascending = chronological).
    posts: list[dict[str, Any]] = []
    for post_id in order:
        post = posts_map.get(post_id)
        if post is None:
            continue
        if post.get("id") == exclude_post_id:
            continue
        posts.append(post)

    # order from the API is newest-first; sort by create_at ascending.
    posts.sort(key=lambda p: p.get("create_at", 0))

    # Keep only the most recent N messages.
    if len(posts) > max_messages:
        posts = posts[-max_messages:]

    logger.info(
        "get_thread_messages: root_id=%s, total_in_thread=%d, returned=%d",
        root_id,
        len(posts_map),
        len(posts),
    )
    return posts
