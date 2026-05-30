"""OpenCode AI integration.

All direct usage of the ``opencode_ai`` SDK and the OpenCode HTTP API is
encapsulated here.  Other modules interact with OpenCode exclusively
through the :class:`OpenCodeClient` facade, which implements
:class:`~mm_agent_bridge.clients.base.AgentClient`.

If a ``session_id`` is provided, the client attempts to use that existing
session.  If the session is unavailable (e.g. 404), a new session is
created automatically and a WARNING is logged with the new session info.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from opencode_ai import AsyncOpencode

from .base import AgentClient

logger = logging.getLogger(__name__)


class OpenCodeClient(AgentClient):
    """AgentClient implementation backed by an OpenCode session."""

    def __init__(
        self,
        *,
        base_url: str,
        session_id: str = "",
        model_id: str,
        provider_id: str,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session_id = session_id
        self._model_id = model_id
        self._provider_id = provider_id
        self._sdk = AsyncOpencode(base_url=base_url)
        self._session_validated = False

    async def chat(self, text: str) -> str:
        """Send *text* to the OpenCode session and return the reply."""
        await self._ensure_session()
        assistant_msg_id = await self._send_message(text)
        return await self._extract_response(assistant_msg_id)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def _ensure_session(self) -> None:
        """Validate the session exists, or create a new one.

        Called lazily on the first ``chat()`` call.  If the configured
        session_id is missing or unavailable, a new session is created
        and a WARNING is logged.
        """
        if self._session_validated:
            return

        if self._session_id:
            # Try to verify the session exists by fetching its messages.
            try:
                url = f"{self._base_url}/session/{self._session_id}/message"
                async with httpx.AsyncClient() as http:
                    resp = await http.get(url)
                    resp.raise_for_status()
                self._session_validated = True
                logger.info(
                    "_ensure_session: session_id=%s is valid",
                    self._session_id,
                )
                return
            except Exception:
                logger.warning(
                    "_ensure_session: session_id=%s is unavailable, "
                    "creating a new session instead",
                    self._session_id,
                    exc_info=True,
                )

        # Create a new session.
        new_session = await self._sdk.session.create()
        self._session_id = new_session.id
        self._session_validated = True
        logger.warning(
            "_ensure_session: created NEW session (session_id=%s). "
            "Update OPENCODE_SESSION_ID to reuse this session.",
            self._session_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_message(self, text: str) -> str:
        """Send *text* and return the assistant message ID."""
        logger.info(
            "send_message: session_id=%s, model_id=%s, provider_id=%s, text=%r",
            self._session_id,
            self._model_id,
            self._provider_id,
            text[:120],
        )
        assistant_msg = await self._sdk.session.chat(
            self._session_id,
            model_id=self._model_id,
            provider_id=self._provider_id,
            parts=[{"type": "text", "text": text}],
        )
        logger.info(
            "send_message: chat() returned — id=%s, role=%s",
            getattr(assistant_msg, "id", None),
            getattr(assistant_msg, "role", None),
        )
        return assistant_msg.id

    async def _extract_response(self, assistant_message_id: str) -> str:
        """Extract the assistant's text from the messages endpoint.

        Uses raw HTTP (httpx) instead of ``session.messages()`` because the
        SDK's response parser has a Python 3.14 compatibility issue with
        discriminated unions (``typing.Union`` is immutable).
        """
        logger.info(
            "extract_response: fetching messages for session_id=%s, looking for msg_id=%s",
            self._session_id,
            assistant_message_id,
        )

        url = f"{self._base_url}/session/{self._session_id}/message"
        logger.info("extract_response: GET %s", url)

        async with httpx.AsyncClient() as http:
            resp = await http.get(url)
            resp.raise_for_status()
            items: list[dict[str, Any]] = resp.json()

        logger.info(
            "extract_response: received %d message items from API",
            len(items),
        )

        # API returns items shaped as {"info": {"id", "role", ...}, "parts": [...]}.
        if items:
            first_info = items[0].get("info", {})
            last_info = items[-1].get("info", {})
            logger.info(
                "extract_response: messages range — first(id=%s, role=%s) ... last(id=%s, role=%s)",
                first_info.get("id"),
                first_info.get("role"),
                last_info.get("id"),
                last_info.get("role"),
            )

        parts_text: list[str] = []

        # Find the matching assistant message by ID.
        for item in items:
            info = item.get("info", {})
            if info.get("id") == assistant_message_id:
                msg_parts = item.get("parts", [])
                logger.info(
                    "extract_response: found matching message id=%s, parts_count=%d",
                    assistant_message_id,
                    len(msg_parts),
                )
                for part in msg_parts:
                    if part.get("type") == "text":
                        parts_text.append(part.get("text", ""))
                    else:
                        logger.info("extract_response: skipping part type=%s", part.get("type"))
                break

        if parts_text:
            result = "\n".join(parts_text)
            logger.info("extract_response: extracted %d text parts, total_length=%d", len(parts_text), len(result))
            return result

        logger.info(
            "extract_response: no parts found for msg_id=%s, trying fallback to latest assistant",
            assistant_message_id,
        )

        # Fallback: return the last assistant message's text.
        for item in reversed(items):
            info = item.get("info", {})
            if info.get("role") == "assistant":
                msg_parts = item.get("parts", [])
                logger.info(
                    "extract_response: fallback — checking assistant msg id=%s, parts_count=%d",
                    info.get("id"),
                    len(msg_parts),
                )
                for part in msg_parts:
                    if part.get("type") == "text":
                        parts_text.append(part.get("text", ""))
                if parts_text:
                    result = "\n".join(parts_text)
                    logger.info("extract_response: fallback extracted %d parts, total_length=%d", len(parts_text), len(result))
                    return result

        logger.info("extract_response: FAILED to extract any text from %d items", len(items))
        return "(No response text could be extracted from the assistant.)"
