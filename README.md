# mm-agent-bridge

Mattermost bot that bridges `@ai-agent` mentions to an AI coding agent and replies in-thread. Supports two backends: [OpenCode](https://opencode.ai) and [GitHub Copilot](https://github.com/features/copilot).

## How it works

1. The bot connects to Mattermost via websocket and listens for `@ai-agent` mentions.
2. Incoming mentions are placed into an `asyncio.Queue` and processed **one at a time** (serial queue).
3. Each message is forwarded to the configured agent backend (`AgentClient.chat()`).
4. The assistant's response is posted back as an in-thread reply on Mattermost.

If a new message arrives while the bot is busy, the sender sees a "queued" notice.

## Prerequisites

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Docker](https://docs.docker.com/get-docker/) (only for local Mattermost)
- One of:
  - A running [OpenCode](https://opencode.ai) server with an active session
  - A GitHub account with [Copilot](https://github.com/features/copilot) access

## Quick start

### 1. Clone and install

```bash
git clone <repo-url>
cd mm-agent-bridge
uv sync
```

### 2. Start local Mattermost (optional)

```bash
docker-compose --profile local up
```

Mattermost will be available at `http://localhost:8065`.

> **Note**: The preview image is `linux/amd64` only. On Apple Silicon it runs via Rosetta and takes ~30s to start.

### 3. Create a bot account and token

It is recommended to create a **dedicated bot account** in Mattermost. The bot filters out its own messages to prevent infinite reply loops, so you must use a **different account** to send `@` mentions.

1. Log in to Mattermost as an admin.
2. Go to **System Console > Integrations > Bot Accounts** and enable bot account creation.
3. Go to **Integrations > Bot Accounts > Add Bot Account**.
   - **Username**: set to the value of `BOT_MENTION_NAME` (e.g. `ai-agent`).
   - **Role**: choose **Member** (or **System Admin** if needed).
   - Save, and copy the generated **access token** — this is your `MM_TOKEN`.
4. Invite the bot account to the channels where you want it to respond.

> **Tip**: If you don't have the Bot Accounts feature, you can also create a regular user account, then generate a **personal access token** under **Profile > Security > Personal Access Tokens**.

### 4. Configure the agent backend

Copy `.env.example` and edit it:

```bash
cp .env.example .env
```

The `AGENT_TYPE` variable determines which backend to use. See below for backend-specific setup.

---

## Agent backends

### OpenCode

The bot connects to a local [OpenCode](https://opencode.ai) session. OpenCode must be running before you start the bot.

If the configured session ID is unavailable or not set, the bot **automatically creates a new session** and logs a WARNING with the new session ID.

#### Setup

1. Install and start OpenCode:

   ```bash
   # Start the OpenCode TUI in your project directory
   opencode
   ```

2. (Optional) Get an existing session ID. In the OpenCode TUI, the session ID is displayed in the status bar, or you can query the API:

   ```bash
   curl http://localhost:36000/session | jq
   ```

3. Configure `.env`:

   ```env
   AGENT_TYPE=opencode

   OPENCODE_BASE_URL=http://localhost:36000
   OPENCODE_SESSION_ID=<session-id>          # optional; creates new if empty/invalid
   OPENCODE_MODEL_ID=claude-sonnet-4-20250514
   OPENCODE_PROVIDER_ID=anthropic
   ```

4. **Verify connectivity** before starting the bot:

   ```bash
   uv run scripts/debug_opencode.py "hello, are you there?"
   ```

   This sends a single message to the OpenCode session and prints the response. If you see the assistant's reply, the connection is working. If it hangs, check that the OpenCode TUI is running and not waiting for a permission prompt.

   You can also send any custom message:

   ```bash
   uv run scripts/debug_opencode.py "explain the project structure"
   ```

> **Gotcha**: `session.chat()` blocks until the LLM completes. If the OpenCode session hits a permission prompt (e.g. accessing files outside workspace), the call will hang until you approve it in the TUI.

---

### GitHub Copilot

The bot uses the [`github-copilot-sdk`](https://pypi.org/project/github-copilot-sdk/) (v0.3.0+) which manages a local Copilot CLI subprocess via JSON-RPC. The CLI binary is bundled inside the SDK package — no separate installation needed.

The bot connects to a **pre-existing** Copilot session (similar to OpenCode). Authentication uses the locally installed **Copilot CLI credentials** — no explicit token configuration is required.

#### Setup

1. You need a GitHub account with **Copilot access** (Individual, Business, or Enterprise).

2. Install and authenticate the Copilot CLI:

   ```bash
   # Install via npm (requires Node.js 22+)
   npm install -g @github/copilot

   # Or via Homebrew (macOS/Linux)
   brew install copilot-cli

   # Authenticate (opens browser for GitHub login)
   copilot
   ```

   Alternatively, skip the CLI install and set one of these environment variables:
   - `COPILOT_GITHUB_TOKEN` (highest priority)
   - `GH_TOKEN`
   - `GITHUB_TOKEN`

   The token needs the **Copilot Requests** permission (fine-grained PAT) or `copilot` scope (classic PAT).

3. Get a session ID. You can use an existing Copilot session to preserve conversation history. If no session ID is provided or it's invalid, the bot creates a new session automatically.

4. Configure `.env`:

   ```env
   AGENT_TYPE=copilot

   COPILOT_SESSION_ID=<your-session-id>      # optional; creates new if empty/invalid
   COPILOT_MODEL=gpt-5.4                     # optional, default: gpt-5.4
   ```

5. **Verify connectivity** before starting the bot:

   ```bash
   uv run scripts/debug_copilot.py "hello, are you there?"
   ```

   The script resumes the existing session and sends a message. If you see the assistant's reply, the connection is working. If it fails with an auth error, check that `copilot --version` works or that your token env var is set.

   You can also send any custom message:

   ```bash
   uv run scripts/debug_copilot.py "explain how asyncio.Queue works"
   ```

> **Note**: The bot uses `resume_session()` to reconnect to the existing session on startup, preserving conversation history. If the session is unavailable, a new one is created automatically (WARNING logged with new session ID).

---

### 5. Run the bot

```bash
uv run mm-agent-bridge
```

Then use a **different account** to mention `@ai-agent` in any channel — the bot will reply in-thread.

## Development

### Running tests

```bash
uv run pytest                        # all 72 tests (~0.1s)
uv run pytest tests/unit/ -v         # unit tests only
uv run pytest tests/integration/ -v  # integration tests only
```

No network, Docker, or running services are needed for tests. All external calls are mocked.

### Project structure

```
src/mm_agent_bridge/
  config.py              # Config dataclass loaded from env vars
  mm.py                  # Mattermost helpers (parse events, post replies)
  bot.py                 # AgentBridge class — orchestrates MM + agent
  main.py                # Entry point: loads .env, builds config, starts bot
  clients/
    base.py              # AgentClient ABC (chat(text) -> str interface)
    opencode.py          # OpenCodeClient — OpenCode session backend
    copilot.py           # CopilotClient — GitHub Copilot SDK backend

scripts/
  debug_opencode.py      # Test OpenCode connectivity (no Mattermost needed)
  debug_copilot.py       # Test Copilot connectivity (no Mattermost needed)

tests/
  conftest.py            # Shared fixtures and factory helpers
  unit/                  # Pure logic tests (config, parsing, cleaning, queue)
  integration/           # Multi-component tests (event flow, client chat, end-to-end)
```

## Environment variables reference

### Common (always required)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MM_URL` | Yes | — | Mattermost hostname (no scheme, e.g. `localhost`) |
| `MM_TOKEN` | Yes | — | Bot access token |
| `MM_PORT` | No | `8065` | Server port |
| `MM_SCHEME` | No | `http` | `http` or `https` |
| `BOT_MENTION_NAME` | No | `ai-agent` | Username the bot listens to (without `@`) |
| `AGENT_TYPE` | No | `opencode` | Agent backend: `opencode` or `copilot` |

### OpenCode backend (used when `AGENT_TYPE=opencode`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENCODE_BASE_URL` | No | `http://localhost:36000` | OpenCode server URL |
| `OPENCODE_SESSION_ID` | No | — | Session to connect to; creates new if empty/invalid |
| `OPENCODE_MODEL_ID` | Yes | — | Model identifier (e.g. `claude-sonnet-4-20250514`) |
| `OPENCODE_PROVIDER_ID` | Yes | — | Provider identifier (e.g. `anthropic`) |

### Copilot backend (used when `AGENT_TYPE=copilot`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COPILOT_SESSION_ID` | No | — | Session to resume; creates new if empty/invalid |
| `COPILOT_MODEL` | No | `gpt-5.4` | Model name |

Authentication is handled automatically by the Copilot CLI. Alternatively, set one of `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, or `GITHUB_TOKEN` in your environment.
