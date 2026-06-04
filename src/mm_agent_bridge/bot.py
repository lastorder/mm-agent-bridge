"""Mattermost Agent Bridge.

Bridges Mattermost mentions to an AI coding agent (OpenCode, Copilot, etc.)
and posts the assistant's response back in-thread.

Architecture: single agent session + asyncio.Queue for serial processing.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass, field
from typing import Any

from mattermostdriver import Driver

from .clients import AgentClient, CopilotClient, OpenCodeClient
from .config import Config
from .mm import (
    clean_mention,
    get_thread_messages,
    is_mention_for_bot,
    parse_posted_event,
    post_message,
    post_or_update_reply,
    post_reply,
    update_post_message,
)
from ._patches import _FixedWebsocket

logger = logging.getLogger(__name__)


def _with_host_info(message: str) -> str:
    """Append the current host name to an operational status message."""
    return f"{message} (host: {socket.gethostname()})"


def _build_agent_client(config: Config) -> AgentClient:
    """Instantiate the correct agent client based on *config.agent_type*."""
    if config.agent_type == "copilot":
        return CopilotClient(
            session_id=config.copilot_session_id,
            model=config.copilot_model,
        )
    # Default: opencode
    return OpenCodeClient(
        base_url=config.opencode_base_url,
        session_id=config.opencode_session_id,
        model_id=config.opencode_model_id,
        provider_id=config.opencode_provider_id,
    )


@dataclass
class AgentBridge:
    """Main bot class that ties Mattermost and an AI agent together."""

    config: Config
    driver: Driver = field(init=False, repr=False)
    agent: AgentClient = field(init=False, repr=False)
    queue: asyncio.Queue[dict[str, Any]] = field(init=False, repr=False)
    bot_user_id: str = field(init=False, default="")
    _busy: bool = field(init=False, default=False)
    _goodbye_sent: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.driver = Driver(
            {
                "url": self.config.mm_url,
                "token": self.config.mm_token,
                "scheme": self.config.mm_scheme,
                "port": self.config.mm_port,
                "verify": self.config.mm_scheme == "https",
            }
        )
        self.agent = _build_agent_client(self.config)
        self.queue = asyncio.Queue(maxsize=self.config.queue_max_size)

    # -- public entry point -------------------------------------------------

    def run(self) -> None:
        """Login and start the event loop (blocking)."""
        logger.info("run: logging in to Mattermost at %s:%s", self.config.mm_url, self.config.mm_port)
        self.driver.login()
        # self.bot_user_id = self.driver.users.get_user("me")["id"]
        logger.info("run: logged in as bot_user_id=%s", self.bot_user_id)

        self._send_greeting()

        logger.info("run: starting event loop and queue consumer")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.create_task(self._queue_consumer())
        logger.info("run: connecting websocket...")
        # init_websocket blocks; it will pick up the existing event loop.
        try:
            self.driver.init_websocket(self.handle_websocket_event, websocket_cls=_FixedWebsocket)
        finally:
            self._send_goodbye()

    # -- Greeting / goodbye -------------------------------------------------

    def _send_greeting(self) -> None:
        """Post the greeting message to the configured channel (if enabled)."""
        if not self.config.greeting_enabled:
            return
        logger.info("_send_greeting: posting to channel=%s", self.config.greeting_channel_id)
        post_message(
            self.driver,
            self.config.greeting_channel_id,
            _with_host_info(self.config.greeting_message),
        )

    def _send_goodbye(self) -> None:
        """Post the goodbye message to the configured channel (if enabled)."""
        if not self.config.greeting_enabled or getattr(self, "_goodbye_sent", False):
            return
        logger.info("_send_goodbye: posting to channel=%s", self.config.greeting_channel_id)
        post_message(
            self.driver,
            self.config.greeting_channel_id,
            _with_host_info(self.config.goodbye_message),
        )
        self._goodbye_sent = True

    # -- Mattermost websocket handler ---------------------------------------

    async def handle_websocket_event(self, raw: str) -> None:
        """Callback invoked by mattermostdriver for every websocket event."""
        post = parse_posted_event(raw)
        if post is None:
            return

        # Ignore our own messages.
        if post.get("user_id") == self.bot_user_id:
            logger.info(
                "handle_websocket_event: ignoring own message post_id=%s",
                post.get("id"),
            )
            return

        # Only handle messages that mention the bot.
        if not is_mention_for_bot(post, self.bot_user_id, self.config.bot_mention_name, use_mentions_list=self.config.mention_by_id):
            logger.info(
                "handle_websocket_event: no mention for bot in post_id=%s, skipping",
                post.get("id"),
            )
            return

        # Reject if queue is full (防恶意刷屏).
        if self.queue.full():
            logger.warning(
                "handle_websocket_event: queue full (%d), rejecting post_id=%s",
                self.queue.qsize(),
                post.get("id"),
            )
            mention_prefix = self._get_mention_prefix(post.get("user_id", ""))
            post_reply(
                self.driver,
                channel_id=post["channel_id"],
                root_id=post.get("root_id") or post["id"],
                message=self._with_host_suffix(f"{mention_prefix}{self.config.msg_queue_full}"),
            )
            return

        should_notify_queued = self._busy or self.queue.qsize() > 0

        logger.info(
            "handle_websocket_event: enqueuing post_id=%s from user_id=%s "
            "(queue_size=%d, busy=%s)",
            post.get("id"),
            post.get("user_id"),
            self.queue.qsize(),
            self._busy,
        )
        await self.queue.put(post)

        # Notify the user when this request will wait behind existing work.
        if should_notify_queued:
            logger.info("handle_websocket_event: request is queued, posting queued notice")
            mention_prefix = self._get_mention_prefix(post.get("user_id", ""))
            queued_post_id = post_reply(
                self.driver,
                channel_id=post["channel_id"],
                root_id=post.get("root_id") or post["id"],
                message=self._with_host_suffix(f"{mention_prefix}{self.config.msg_queued}"),
            )
            post["_ack_post_id"] = queued_post_id

    # -- Queue consumer (serial processing) ---------------------------------

    async def _queue_consumer(self) -> None:
        """Process enqueued posts one at a time, forever."""
        logger.info("_queue_consumer: started, waiting for messages...")
        while True:
            post = await self.queue.get()
            logger.info(
                "_queue_consumer: dequeued post_id=%s (remaining=%d)",
                post.get("id"),
                self.queue.qsize(),
            )
            await self._process_post(post)
            self.queue.task_done()

    async def _process_post(self, post: dict[str, Any]) -> None:
        """Send a single post to the agent and reply with the result."""
        self._busy = True
        channel_id = post["channel_id"]
        root_id = post.get("root_id") or post["id"]
        text = clean_mention(post.get("message", ""), self.config.bot_mention_name)
        mention_prefix = self._get_mention_prefix(post.get("user_id", ""))

        if not text:
            logger.info("_process_post: empty text after cleaning mention, replying with notice")
            post_reply(self.driver, channel_id, root_id, self._with_host_suffix(self.config.msg_empty))
            self._busy = False
            return

        # Prepend sender identity so the agent knows who is asking.
        sender_username = self._lookup_username(post.get("user_id", ""))
        text = f"@{sender_username}: {text}"

        # Prepend thread context when the message is in an existing thread.
        if post.get("root_id"):
            context = self._build_thread_context(post)
            if context:
                text = f"{context}\n{text}"

        # Post an acknowledgment reply first, then update it with the response.
        # If the queued notice already created a post, reuse it.
        ack_post_id = post.get("_ack_post_id", "")
        ack_message = self._with_host_suffix(f"{mention_prefix}{self.config.msg_processing}")
        if ack_post_id:
            update_post_message(self.driver, ack_post_id, ack_message)
        else:
            ack_post_id = post_reply(
                self.driver, channel_id, root_id, ack_message
            )

        try:
            logger.info(
                "_process_post: sending to agent (%s), text=%r",
                self.config.agent_type,
                text[:120],
            )
            response_text = await self.agent.chat(text)
            logger.info(
                "_process_post: got response (length=%d): %r",
                len(response_text),
                response_text[:200],
            )
            post_or_update_reply(
                self.driver,
                channel_id,
                root_id,
                ack_post_id,
                self._with_host_suffix(f"{mention_prefix}{response_text}"),
            )

        except Exception:
            logger.exception("_process_post: ERROR processing post_id=%s", post.get("id"))
            post_or_update_reply(
                self.driver,
                channel_id,
                root_id,
                ack_post_id,
                self._with_host_suffix(f"{mention_prefix}{self.config.msg_error}"),
            )
        finally:
            self._busy = False
            logger.info("_process_post: done, busy=False")

    def _build_thread_context(self, post: dict[str, Any]) -> str:
        """Fetch thread messages and format them as structured context.

        Returns a formatted string like:
            [Thread context]
            @alice: Hello
            @bot: Hi there
            ...

            [Current request]

        Returns ``""`` if there are no thread messages or on failure.
        """
        thread_posts = get_thread_messages(
            self.driver,
            post["root_id"],
            exclude_post_id=post.get("id", ""),
            max_messages=self.config.thread_context_max_messages,
        )
        if not thread_posts:
            return ""

        # Cache username lookups within a single context build.
        user_cache: dict[str, str] = {}
        lines: list[str] = ["[Thread context]"]

        for tp in thread_posts:
            uid = tp.get("user_id", "")
            if uid not in user_cache:
                user_cache[uid] = self._lookup_username(uid)
            username = user_cache[uid]
            message = tp.get("message", "").strip()
            lines.append(f"@{username}: {message}")

        lines.append("")
        lines.append("[Current request]")
        return "\n".join(lines)

    def _lookup_username(self, user_id: str) -> str:
        """Look up a username by user_id, returning the user_id on failure."""
        if not user_id:
            return "unknown"
        try:
            user = self.driver.users.get_user(user_id)
            return user.get("username", user_id)
        except Exception:
            logger.warning(
                "_lookup_username: failed to look up user_id=%s",
                user_id,
                exc_info=True,
            )
            return user_id

    def _get_mention_prefix(self, user_id: str) -> str:
        """Return ``@username `` for *user_id*, or ``""`` on failure."""
        if not user_id:
            return ""
        try:
            user = self.driver.users.get_user(user_id)
            username = user.get("username", "")
            if username:
                return f"@{username} "
        except Exception:
            logger.warning(
                "_get_mention_prefix: failed to look up user_id=%s",
                user_id,
                exc_info=True,
            )
        return ""

    def _with_host_suffix(self, message: str) -> str:
        """Append a newline and host info if ``msg_show_host`` is enabled."""
        if not self.config.msg_show_host:
            return message
        return f"{message}\n(host: {socket.gethostname()})"
