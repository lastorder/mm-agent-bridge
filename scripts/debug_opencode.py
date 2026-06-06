#!/usr/bin/env python3
"""Standalone debug script for the OpenCode integration.

Usage:
    uv run scripts/debug_opencode.py "your message here"
    uv run scripts/debug_opencode.py                      # uses default prompt

Environment variables (see .env.example):
    OPENCODE_BASE_URL, OPENCODE_MODEL_ID, OPENCODE_PROVIDER_ID (required)
    OPENCODE_SESSION_ID, OPENCODE_VARIANT, OPENCODE_SERVER_PASSWORD,
    OPENCODE_SERVER_USERNAME (optional)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from mm_agent_bridge.clients.opencode import OpenCodeClient
from mm_agent_bridge.config import OpenCodeConfig


async def main() -> None:
    try:
        oc = OpenCodeConfig.from_env()
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "请输出你的工作目录，你当前可用的skills，以及mcp tools"

    print(f"[config] base_url={oc.base_url} session={oc.session_id or '(will create new)'} model={oc.model_id}")
    print(f"[config] auth={'enabled' if oc.password else 'none'} variant={oc.variant or '(default)'}")
    print(f"[input]  {text!r}")
    print()

    client = OpenCodeClient(**asdict(oc))
    try:
        response = await client.chat(text)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        sys.exit(1)

    print(response)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
