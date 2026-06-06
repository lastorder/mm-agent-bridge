"""GitHub Copilot integration via ``github-copilot-sdk``.

All direct usage of the Copilot SDK is encapsulated here.
Other modules interact with Copilot exclusively through the
:class:`CopilotClient` facade, which implements
:class:`~mm_agent_bridge.clients.base.AgentClient`.

The SDK manages a local Copilot CLI subprocess via JSON-RPC.
Authentication uses the locally installed Copilot CLI credentials
(via ``copilot`` command or environment variables
``COPILOT_GITHUB_TOKEN`` / ``GH_TOKEN`` / ``GITHUB_TOKEN``).

If a ``session_id`` is provided, the client resumes the existing
session (preserving conversation history).  Otherwise, a new session
is created on the first ``chat()`` call.
"""

from __future__ import annotations

import logging

from copilot import CopilotClient as SdkClient
from copilot.session import AssistantMessageData, CopilotSession, PermissionHandler

from .base import AgentClient
from .factory import register

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-5.4"


@register("copilot")
class CopilotClient(AgentClient):
    """AgentClient implementation backed by GitHub Copilot SDK.

    Uses the locally installed Copilot CLI for authentication.
    No explicit token is required — the SDK picks up credentials from
    the Copilot CLI login state or environment variables
    (``COPILOT_GITHUB_TOKEN``, ``GH_TOKEN``, ``GITHUB_TOKEN``).

    If *session_id* is provided, the client resumes that existing
    session via ``resume_session()``.  Otherwise, a fresh session is
    created via ``create_session()``.
    """

    def __init__(
        self,
        *,
        session_id: str = "",
        model: str = _DEFAULT_MODEL,
        timeout: float = 120.0,
    ) -> None:
        self._session_id = session_id
        self._model = model
        self._timeout = timeout
        self._sdk_client: SdkClient | None = None
        self._session: CopilotSession | None = None

    @classmethod
    def from_config(cls, config) -> "CopilotClient":
        """Create from a :class:`~mm_agent_bridge.config.Config` instance."""
        from dataclasses import asdict

        cc = config.copilot
        assert cc is not None, "Config.copilot is required for copilot backend"
        return cls(**asdict(cc))

    async def chat(self, text: str) -> str:
        """Send *text* to GitHub Copilot and return the reply.

        On the first call, the SDK subprocess and session are created
        (or resumed) lazily.  Subsequent calls reuse the same session,
        so the model retains conversation context.
        """
        await self._ensure_session()
        assert self._session is not None  # for type-checker

        logger.info(
            "chat: sending to Copilot model=%s, text=%r",
            self._model,
            text[:120],
        )

        response = await self._session.send_and_wait(
            text, timeout=self._timeout,
        )

        reply_text = self._extract_content(response)
        logger.info(
            "chat: got response (length=%d): %r",
            len(reply_text),
            reply_text[:200],
        )
        return reply_text

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _ensure_session(self) -> None:
        """Start the SDK client and create/resume a session if not already done."""
        if self._session is not None:
            return

        logger.info(
            "_ensure_session: starting Copilot SDK client (model=%s, session_id=%s)",
            self._model,
            self._session_id or "(new)",
        )
        self._sdk_client = SdkClient()
        await self._sdk_client.start()

        if self._session_id:
            # Try to resume the existing session.
            try:
                self._session = await self._sdk_client.resume_session(
                    self._session_id,
                    on_permission_request=PermissionHandler.approve_all,
                    model=self._model,
                )
                logger.info(
                    "_ensure_session: resumed session (session_id=%s)",
                    self._session.session_id,
                )
                return
            except Exception:
                logger.warning(
                    "_ensure_session: failed to resume session_id=%s, "
                    "creating a new session instead",
                    self._session_id,
                    exc_info=True,
                )

        # Create a new session (either no session_id or resume failed).
        self._session = await self._sdk_client.create_session(
            on_permission_request=PermissionHandler.approve_all,
            model=self._model,
        )
        logger.warning(
            "_ensure_session: created NEW session (session_id=%s). "
            "Update COPILOT_SESSION_ID to reuse this session.",
            self._session.session_id,
        )

    async def stop(self) -> None:
        """Gracefully stop the SDK subprocess.

        Safe to call multiple times or if never started.
        """
        if self._session is not None:
            try:
                await self._session.disconnect()
            except Exception:
                logger.debug("stop: ignoring error during session disconnect", exc_info=True)
            self._session = None

        if self._sdk_client is not None:
            try:
                await self._sdk_client.stop()
            except Exception:
                logger.debug("stop: ignoring error during client stop", exc_info=True)
            self._sdk_client = None

        logger.info("stop: Copilot SDK client stopped")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_content(response) -> str:
        """Pull the text content out of a SessionEvent response."""
        if response is None:
            logger.warning("_extract_content: response is None")
            return "(No response from Copilot.)"

        data = response.data
        if isinstance(data, AssistantMessageData):
            if data.content:
                return data.content
            logger.warning("_extract_content: empty content in AssistantMessageData")
            return "(Empty response from Copilot.)"

        # Fallback: duck-type check for objects with a ``content`` attribute
        # (e.g. test fakes that are not actual AssistantMessageData instances).
        content = getattr(data, "content", None)
        if content is not None:
            if content:
                return content
            logger.warning("_extract_content: empty content (duck-typed)")
            return "(Empty response from Copilot.)"

        logger.warning(
            "_extract_content: unexpected event data type: %s",
            type(data).__name__,
        )
        return "(Unexpected response type from Copilot.)"
