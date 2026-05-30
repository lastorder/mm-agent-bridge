"""OpenCode AI integration.

All direct usage of the ``opencode_ai`` SDK is encapsulated here.
Other modules interact with OpenCode exclusively through the
:class:`OpenCodeClient` facade, which implements
:class:`~mm_agent_bridge.clients.base.AgentClient`.

If a ``session_id`` is provided, the client attempts to use that existing
session.  If the session is unavailable (e.g. 404), a new session is
created automatically and a WARNING is logged with the new session info.

Note: the SDK uses ``with_raw_response`` throughout because the SDK's
Pydantic ``construct()`` silently produces ``None`` fields on Python 3.14
when the API response uses an envelope format (``{"info": …, "parts": …}``)
that doesn't match the flat model definitions.  Accessing ``.json()`` on the
raw response bypasses Pydantic entirely and gives us the actual dict.
"""

from __future__ import annotations

import logging
from typing import Any

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
        self._session_id = session_id
        self._model_id = model_id
        self._provider_id = provider_id
        self._sdk = AsyncOpencode(base_url=base_url)
        self._session_validated = False

    async def chat(self, text: str) -> str:
        """Send *text* to the OpenCode session and return the reply."""
        await self._ensure_session()
        msg_id, response_text = await self._send_message(text)
        if response_text:
            return response_text
        # Fallback: fetch from the messages listing if the POST response
        # didn't contain text parts.
        logger.info("chat: POST response had no text parts, falling back to _extract_response")
        return await self._extract_response(msg_id)

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
            try:
                await self._sdk.session.with_raw_response.messages(self._session_id)
                self._session_validated = True
                logger.info("_ensure_session: session_id=%s is valid", self._session_id)
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

    @staticmethod
    def _check_message_error(info: dict[str, Any]) -> None:
        """Raise if the assistant message carries an error from the LLM.

        The OpenCode API returns HTTP 200 even when the underlying LLM
        call fails.  The error is embedded in ``info.error``.  This method
        detects that and raises a ``RuntimeError`` so the caller can
        surface it to the user instead of silently returning stale content.
        """
        error = info.get("error")
        if not error:
            return
        error_name = error.get("name", "UnknownError")
        error_data = error.get("data", {})
        error_message = error_data.get("message", str(error))
        status_code = error_data.get("statusCode", "")
        detail = f"{error_name}: {error_message}"
        if status_code:
            detail += f" (status {status_code})"
        logger.error("_check_message_error: LLM call failed — %s", detail)
        raise RuntimeError(f"OpenCode LLM error — {detail}")

    @staticmethod
    def _extract_text(parts: list[dict[str, Any]]) -> str:
        """Join all ``text`` parts into a single string."""
        return "\n".join(
            p.get("text", "") for p in parts if p.get("type") == "text"
        )

    async def _send_message(self, text: str) -> tuple[str, str]:
        """Send *text* and return ``(msg_id, response_text)``.

        Raises ``RuntimeError`` if the response carries an LLM-level error
        (e.g. unsupported model, auth failure).
        """
        logger.info(
            "send_message: session_id=%s, model_id=%s, provider_id=%s, text=%r",
            self._session_id,
            self._model_id,
            self._provider_id,
            text[:120],
        )

        # chat() blocks until the LLM completes; disable timeout.
        raw = await self._sdk.session.with_raw_response.chat(
            self._session_id,
            model_id=self._model_id,
            provider_id=self._provider_id,
            parts=[{"type": "text", "text": text}],
            timeout=None,
        )
        data: dict[str, Any] = await raw.json()

        # Response envelope: {"info": {"id", "role", "error"?, …}, "parts": […]}
        info = data.get("info", {})
        msg_id = info.get("id", "")

        logger.info(
            "send_message: response — id=%s, role=%s, has_error=%s",
            msg_id,
            info.get("role"),
            bool(info.get("error")),
        )

        self._check_message_error(info)

        response_text = self._extract_text(data.get("parts") or [])
        if response_text:
            logger.info("send_message: extracted text, length=%d", len(response_text))
        else:
            logger.info("send_message: no text parts in POST response")

        return msg_id, response_text

    async def _extract_response(self, assistant_message_id: str) -> str:
        """Extract the assistant's text from the messages listing.

        Looks up the specific message by *assistant_message_id*.  Does NOT
        fall back to scanning old messages — that would risk returning stale
        content from an unrelated past conversation.
        """
        if not assistant_message_id:
            logger.error("extract_response: no message ID provided")
            return "(No response — assistant message ID is missing.)"

        logger.info(
            "extract_response: session_id=%s, looking for msg_id=%s",
            self._session_id,
            assistant_message_id,
        )

        raw = await self._sdk.session.with_raw_response.messages(self._session_id)
        items: list[dict[str, Any]] = await raw.json()
        logger.info("extract_response: received %d message items", len(items))

        for item in items:
            info = item.get("info", {})
            if info.get("id") != assistant_message_id:
                continue

            self._check_message_error(info)

            response_text = self._extract_text(item.get("parts") or [])
            if response_text:
                logger.info("extract_response: extracted text, length=%d", len(response_text))
                return response_text

            logger.warning(
                "extract_response: message %s found but has no text parts",
                assistant_message_id,
            )
            return "(No response text in the assistant message.)"

        logger.error(
            "extract_response: message %s not found in %d items",
            assistant_message_id,
            len(items),
        )
        return "(No response — assistant message not found.)"
