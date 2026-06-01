"""Shared fixtures and helper factories for all tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mm_agent_bridge.bot import AgentBridge
from mm_agent_bridge.config import Config

# ---------------------------------------------------------------------------
# Config fixture
# ---------------------------------------------------------------------------

BOT_USER_ID = "bot-user-id-123"


@pytest.fixture
def config() -> Config:
    return Config(
        mm_url="localhost",
        mm_token="test-token",
        mm_port=8065,
        mm_scheme="http",
        agent_type="opencode",
        opencode_base_url="http://localhost:36000",
        opencode_session_id="test-session-id",
        opencode_model_id="test-model",
        opencode_provider_id="test-provider",
    )


# ---------------------------------------------------------------------------
# Mock Mattermost Driver
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_driver() -> MagicMock:
    driver = MagicMock()

    def _get_user(user_id: str) -> dict[str, str]:
        if user_id == "me":
            return {"id": BOT_USER_ID, "username": "ai-agent"}
        return {"id": user_id, "username": f"user-{user_id}"}

    driver.users.get_user.side_effect = _get_user
    driver.posts.create_post.return_value = {"id": "new-post-id"}
    return driver


# ---------------------------------------------------------------------------
# Mock OpenCode client
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_opencode() -> AsyncMock:
    """Mock OpenCodeClient — ``chat()`` returns text directly."""
    client = AsyncMock()
    client.chat.return_value = "Here is my response."
    return client


# ---------------------------------------------------------------------------
# Mock SDK for OpenCodeClient._extract_response tests
# ---------------------------------------------------------------------------

# Default messages JSON that SDK session.with_raw_response.messages() will return.
_DEFAULT_MESSAGES_JSON: list[dict[str, Any]] = [
    {"info": {"id": "user-msg-1", "role": "user"}, "parts": [{"type": "text", "text": "hello"}]},
    {"info": {"id": "assistant-msg-1", "role": "assistant"}, "parts": [{"type": "text", "text": "Here is my response."}]},
]


@pytest.fixture
def mock_sdk_messages():
    """Build a mock ``_sdk`` whose ``session.with_raw_response.messages()``
    returns data from ``container.response_json``.

    Returns a :class:`_SdkMockContainer` with:

    * ``response_json`` — mutable list of message dicts; tests can
      override this before calling methods that fetch messages.
    * ``sdk`` — a :class:`~unittest.mock.MagicMock` to assign to
      ``client._sdk``.
    """
    container = _SdkMockContainer(response_json=list(_DEFAULT_MESSAGES_JSON))

    class _FakeResponse:
        def __init__(self, data: Any):
            self._data = data

        async def json(self) -> Any:
            return self._data

    async def _mock_messages(session_id: str) -> _FakeResponse:
        return _FakeResponse(container.response_json)

    sdk = MagicMock()
    sdk.session.with_raw_response.messages = AsyncMock(side_effect=_mock_messages)
    container.sdk = sdk
    return container


@dataclass
class _SdkMockContainer:
    """Mutable container so tests can change the SDK mock response."""
    response_json: list[dict[str, Any]]
    sdk: Any = None


# ---------------------------------------------------------------------------
# Bot fixture (fully wired with mocks)
# ---------------------------------------------------------------------------


@pytest.fixture
def bot(config: Config, mock_driver: MagicMock, mock_opencode: AsyncMock) -> AgentBridge:
    """AgentBridge with mocked external dependencies."""
    b = AgentBridge.__new__(AgentBridge)
    b.config = config
    b.driver = mock_driver
    b.agent = mock_opencode
    b.bot_user_id = BOT_USER_ID
    b._busy = False
    b._goodbye_sent = False

    import asyncio

    b.queue = asyncio.Queue()
    return b


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_posted_event(
    *,
    message: str = "hello",
    channel_id: str = "ch-1",
    post_id: str = "post-1",
    user_id: str = "user-1",
    mentions: list[str] | None = None,
    root_id: str = "",
) -> str:
    """Build a raw Mattermost websocket ``posted`` event JSON string."""
    post = {
        "id": post_id,
        "channel_id": channel_id,
        "user_id": user_id,
        "message": message,
        "root_id": root_id,
    }
    data: dict[str, Any] = {"post": json.dumps(post)}
    if mentions is not None:
        data["mentions"] = json.dumps(mentions)
    return json.dumps({"event": "posted", "data": data})


def make_non_posted_event(event_type: str = "typing") -> str:
    """Build a raw Mattermost websocket event that is NOT ``posted``."""
    return json.dumps({"event": event_type, "data": {}})


# -- JSON factories for SDK mock (OpenCodeClient._extract_response tests) --


def make_assistant_message_json(
    *texts: str, msg_id: str = "assistant-msg-1"
) -> dict[str, Any]:
    """Build an assistant message item (as returned by the API).

    API format: {"info": {"id", "role", ...}, "parts": [...]}
    """
    parts = [{"type": "text", "text": t, "id": f"part-{i}", "messageID": msg_id, "sessionID": "s"} for i, t in enumerate(texts)]
    return {"info": {"id": msg_id, "role": "assistant"}, "parts": parts}


def make_user_message_json(text: str, msg_id: str = "user-msg-1") -> dict[str, Any]:
    """Build a user message item (as returned by the API).

    API format: {"info": {"id", "role", ...}, "parts": [...]}
    """
    return {"info": {"id": msg_id, "role": "user"}, "parts": [{"type": "text", "text": text, "id": "part-0", "messageID": msg_id, "sessionID": "s"}]}
