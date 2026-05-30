# AGENTS.md

## Project overview

Mattermost bot that forwards `@ai-agent` mentions to a **single, pre-existing** OpenCode session and replies in-thread. Messages are processed serially via an `asyncio.Queue` — no concurrent OpenCode calls.

## Key commands

```bash
uv sync                              # install all deps (including dev group)
uv run pytest                        # run all 69 tests (~0.1s, no network needed)
uv run pytest tests/unit/ -v         # unit tests only
uv run pytest tests/integration/ -v  # integration tests only
uv run mm-agent-bridge               # start the bot (requires .env)
docker-compose --profile local up    # start local Mattermost on :8065
```

## Architecture

- **No dynamic session creation**: the bot connects to one fixed OpenCode session configured via `OPENCODE_SESSION_ID`. Do not add session-creation logic.
- **Serial queue**: `_process_post` sets `_busy=True`, calls `AgentClient.chat()`, posts response to MM, then sets `_busy=False`. Concurrent requests are queued with a user-visible "queued" notice.
- **Agent client abstraction**: `AgentClient` (ABC in `clients/base.py`) defines the `chat(text) -> str` interface. `OpenCodeClient` and `CopilotClient` are the two implementations. All `opencode_ai` SDK usage is isolated in `clients/opencode.py`. Other modules depend on `AgentClient`, never on SDK imports directly.
- **Backend selection**: `AGENT_TYPE` env var (`opencode` or `copilot`) determines which client is instantiated at startup via `_build_agent_client()` in `bot.py`.

## Module map

| Path | Role |
|------|------|
| `src/mm_agent_bridge/config.py` | `Config` dataclass, loaded from env vars via `Config.from_env()` |
| `src/mm_agent_bridge/clients/` | Agent client subpackage |
| `src/mm_agent_bridge/clients/base.py` | `AgentClient` ABC — defines `chat(text) -> str` interface |
| `src/mm_agent_bridge/clients/opencode.py` | `OpenCodeClient` — OpenCode session backend |
| `src/mm_agent_bridge/clients/copilot.py` | `CopilotClient` — GitHub Copilot chat completions backend |
| `src/mm_agent_bridge/mm.py` | Mattermost integration — `clean_mention`, `parse_posted_event`, `is_mention_for_bot`, `post_reply` |
| `src/mm_agent_bridge/bot.py` | `AgentBridge` class — orchestrates MM and agent via asyncio.Queue |
| `src/mm_agent_bridge/main.py` | Entry point — loads `.env`, builds config, calls `bot.run()` |
| `scripts/debug_opencode.py` | Standalone debug script for OpenCode module |
| `scripts/debug_copilot.py` | Standalone debug script for Copilot module |
| `tests/conftest.py` | All shared fixtures and factory helpers |

## Testing conventions

- **pytest-asyncio in auto mode** (`asyncio_mode = "auto"` in pyproject.toml) — `@pytest.mark.asyncio` is optional but harmless; all async test functions are collected automatically.
- The `bot` fixture bypasses `__post_init__` (uses `AgentBridge.__new__`) and injects `MagicMock`/`AsyncMock` for the driver and OpenCode client. Always use this fixture; never instantiate `AgentBridge(config)` directly in tests.
- Factory helpers (`make_posted_event`, `make_assistant_message_json`, etc.) are in `tests/conftest.py` and imported as `from tests.conftest import ...`. The `tests/` directory has `__init__.py` files to support this.
- No tests require network, Docker, or running services. All external calls are mocked.

## Environment variables

Required — the bot exits on startup if any required var is missing:

| Variable | Example |
|----------|---------|
| `MM_URL` | `localhost` (hostname only, no scheme) |
| `MM_TOKEN` | Mattermost personal access token |
| `AGENT_TYPE` | `opencode` (default) or `copilot` |

**OpenCode backend** (used when `AGENT_TYPE=opencode`):

| Variable | Example |
|----------|---------|
| `OPENCODE_SESSION_ID` | (optional) Existing session ID; creates new if empty/invalid |
| `OPENCODE_MODEL_ID` | e.g. `claude-sonnet-4-20250514` |
| `OPENCODE_PROVIDER_ID` | e.g. `anthropic` |

**Copilot backend** (used when `AGENT_TYPE=copilot`):

No explicit token is needed. Auth is handled by the local Copilot CLI (`copilot` command) or environment variables (`COPILOT_GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN`).

| Variable | Example |
|----------|---------|
| `COPILOT_SESSION_ID` | (optional) Existing session ID to resume; creates new if empty/invalid |
| `COPILOT_MODEL` | (optional) e.g. `gpt-5.4` (default) |

Optional with defaults: `MM_PORT` (8065), `MM_SCHEME` (http), `BOT_MENTION_NAME` (ai-agent), `OPENCODE_BASE_URL` (http://localhost:36000), `COPILOT_MODEL` (gpt-5.4).

## Known gotchas

- `mattermostdriver` (7.3.2, last updated Jan 2022): `driver.init_websocket()` internally calls `loop.run_until_complete()` and blocks. The bot creates its own event loop beforehand and schedules the queue consumer as a task. If this breaks, bypass `init_websocket` and call the lower-level `Websocket` class directly.
- `opencode-ai` is pre-release (`>=0.1.0a36`). API surface may change between versions; pin or check after upgrades.
- `github-copilot-sdk` (`>=0.3.0`): manages a local Copilot CLI subprocess via JSON-RPC. The CLI binary is bundled inside the package. The SDK is fully async; `CopilotClient` creates a session lazily on the first `chat()` call.
- The Mattermost preview Docker image is `linux/amd64` only. On Apple Silicon it runs under Rosetta emulation and is slow to start (~30s).
- OpenCode `session.chat()` blocks until LLM completes. If the session hits a permission prompt (e.g. accessing files outside workspace), the call hangs until approved in the TUI.
