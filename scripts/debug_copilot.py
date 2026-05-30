#!/usr/bin/env python3
"""Standalone debug script for the GitHub Copilot integration.

Usage:
    uv run scripts/debug_copilot.py "your message here"
    uv run scripts/debug_copilot.py                      # defaults to "hello"

Prerequisites:
    - GitHub Copilot CLI installed and authenticated (`copilot --version`)
    - Or set COPILOT_GITHUB_TOKEN / GH_TOKEN / GITHUB_TOKEN env var

Environment variables:
    COPILOT_SESSION_ID  (required) Existing Copilot session ID to resume
    COPILOT_MODEL       (optional) Model name, default: gpt-5.4
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from mm_agent_bridge.clients import CopilotClient


async def main() -> None:
    load_dotenv()

    session_id = os.environ.get("COPILOT_SESSION_ID", "").strip()
    model = os.environ.get("COPILOT_MODEL", "gpt-5.4").strip()

    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "请输出你的工作目录，你当前可用的skills，以及mcp tools"

    print(f"[config] model={model} session_id={session_id}")
    print(f"[config] auth: using local Copilot CLI credentials")
    print(f"[input]  {text!r}")
    print()

    client = CopilotClient(session_id=session_id, model=model)
    try:
        response = await client.chat(text)
        print(response)
    finally:
        await client.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
