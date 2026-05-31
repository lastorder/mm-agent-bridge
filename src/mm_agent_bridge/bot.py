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
    is_mention_for_bot,
    parse_posted_event,
    post_message,
    post_reply,
    update_post_message,
)

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
    opencode: AgentClient = field(init=False, repr=False)
    queue: asyncio.Queue[dict[str, Any]] = field(init=False, repr=False)
    bot_user_id: str = field(init=False, default="")
    _busy: bool = field(init=False, default=False)

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
        self.opencode = _build_agent_client(self.config)
        self.queue = asyncio.Queue()

    # -- public entry point -------------------------------------------------

    def run(self) -> None:
        """Login and start the event loop (blocking)."""
        logger.info("run: logging in to Mattermost at %s:%s", self.config.mm_url, self.config.mm_port)
        self.driver.login()
        self.bot_user_id = self.driver.users.get_user("me")["id"]
        logger.info("run: logged in as bot_user_id=%s", self.bot_user_id)

        self._send_greeting()

        logger.info("run: starting event loop and queue consumer")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.create_task(self._queue_consumer())
        logger.info("run: connecting websocket...")
        # init_websocket blocks; it will pick up the existing event loop.
        try:
            self.driver.init_websocket(self.handle_websocket_event)
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
        if not self.config.greeting_enabled:
            return
        logger.info("_send_goodbye: posting to channel=%s", self.config.greeting_channel_id)
        post_message(
            self.driver,
            self.config.greeting_channel_id,
            _with_host_info(self.config.goodbye_message),
        )

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
        if not is_mention_for_bot(post, self.bot_user_id, self.config.bot_mention_name):
            logger.info(
                "handle_websocket_event: no mention for bot in post_id=%s, skipping",
                post.get("id"),
            )
            return

        logger.info(
            "handle_websocket_event: enqueuing post_id=%s from user_id=%s "
            "(queue_size=%d, busy=%s)",
            post.get("id"),
            post.get("user_id"),
            self.queue.qsize(),
            self._busy,
        )
        await self.queue.put(post)

        # Notify the user if the bot is already busy.
        if self._busy:
            logger.info("handle_websocket_event: bot is busy, posting queued notice")
            post_reply(
                self.driver,
                channel_id=post["channel_id"],
                root_id=post.get("root_id") or post["id"],
                message="Your request has been queued. Please wait...",
            )

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

        if not text:
            logger.info("_process_post: empty text after cleaning mention, replying with notice")
            post_reply(self.driver, channel_id, root_id, "Empty message after removing mention.")
            self._busy = False
            return

        # Post an acknowledgment reply first, then update it with the response.
        ack_post_id = post_reply(
            self.driver, channel_id, root_id, "Processing your request..."
        )

        try:
            logger.info(
                "_process_post: sending to agent (%s), text=%r",
                self.config.agent_type,
                text[:120],
            )
            response_text = await self.opencode.chat(text)
            logger.info(
                "_process_post: got response (length=%d): %r",
                len(response_text),
                response_text[:200],
            )
            update_post_message(self.driver, ack_post_id, response_text)

        except Exception:
            logger.exception("_process_post: ERROR processing post_id=%s", post.get("id"))
            update_post_message(
                self.driver,
                ack_post_id,
                "Sorry, an error occurred while processing your request.",
            )
        finally:
            self._busy = False
            logger.info("_process_post: done, busy=False")
