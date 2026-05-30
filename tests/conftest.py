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
    driver.users.get_user.return_value = {"id": BOT_USER_ID}
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
# Mock httpx for OpenCodeClient._extract_response tests
# ---------------------------------------------------------------------------

# Default messages JSON that httpx.AsyncClient.get() will return.
_DEFAULT_MESSAGES_JSON = [
    {"info": {"id": "user-msg-1", "role": "user"}, "parts": [{"type": "text", "text": "hello"}]},
    {"info": {"id": "assistant-msg-1", "role": "assistant"}, "parts": [{"type": "text", "text": "Here is my response."}]},
]


@pytest.fixture
def mock_httpx_messages(monkeypatch: pytest.MonkeyPatch):
    """Patch httpx.AsyncClient so _extract_response uses mock data.

    Tests can override the response by setting
    ``mock_httpx_messages.response_json`` before calling the method.
    """
    container = _HttpxMockContainer(response_json=_DEFAULT_MESSAGES_JSON)

    class _FakeResponse:
        status_code = 200

        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            return _FakeResponse(container.response_json)

    monkeypatch.setattr("mm_agent_bridge.clients.opencode.httpx.AsyncClient", _FakeAsyncClient)
    return container


@dataclass
class _HttpxMockContainer:
    """Mutable container so tests can change the httpx response."""
    response_json: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Bot fixture (fully wired with mocks)
# ---------------------------------------------------------------------------


@pytest.fixture
def bot(config: Config, mock_driver: MagicMock, mock_opencode: AsyncMock) -> AgentBridge:
    """AgentBridge with mocked external dependencies."""
    b = AgentBridge.__new__(AgentBridge)
    b.config = config
    b.driver = mock_driver
    b.opencode = mock_opencode
    b.bot_user_id = BOT_USER_ID
    b._busy = False

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


# -- JSON factories for httpx mock (OpenCodeClient._extract_response tests) --


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
