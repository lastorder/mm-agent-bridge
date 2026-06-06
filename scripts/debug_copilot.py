#!/usr/bin/env python3
"""Standalone debug script for the GitHub Copilot integration.

Usage:
    uv run scripts/debug_copilot.py "your message here"
    uv run scripts/debug_copilot.py                      # uses default prompt

Prerequisites:
    - GitHub Copilot CLI installed and authenticated (`copilot --version`)
    - Or set COPILOT_GITHUB_TOKEN / GH_TOKEN / GITHUB_TOKEN env var

Environment variables (see .env.example):
    COPILOT_SESSION_ID (optional), COPILOT_MODEL (optional, default: gpt-5.4)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from mm_agent_bridge.clients.copilot import CopilotClient
from mm_agent_bridge.config import CopilotConfig


async def main() -> None:
    cc = CopilotConfig.from_env()

    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "请输出你的工作目录，你当前可用的skills，以及mcp tools"

    print(f"[config] model={cc.model} session_id={cc.session_id or '(will create new)'}")
    print(f"[config] auth: using local Copilot CLI credentials")
    print(f"[input]  {text!r}")
    print()

    client = CopilotClient(**asdict(cc))
    try:
        response = await client.chat(text)
        print(response)
    finally:
        await client.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
