#!/usr/bin/env python3
"""Standalone debug script for the OpenCode integration.

Usage:
    uv run scripts/debug_opencode.py "your message here"
    uv run scripts/debug_opencode.py                      # defaults to "hello"

Environment variables:
    OPENCODE_BASE_URL    (optional) Default: http://localhost:4096
    OPENCODE_SESSION_ID  (optional) Existing session to resume; creates new if empty/invalid
    OPENCODE_MODEL_ID    (required) e.g. claude-sonnet-4-20250514
    OPENCODE_PROVIDER_ID (required) e.g. anthropic
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from mm_agent_bridge.clients import OpenCodeClient


async def main() -> None:
    base_url = os.environ.get("OPENCODE_BASE_URL", "http://localhost:4096").strip()
    session_id = os.environ.get("OPENCODE_SESSION_ID", "").strip()
    model_id = os.environ.get("OPENCODE_MODEL_ID", "").strip()
    provider_id = os.environ.get("OPENCODE_PROVIDER_ID", "").strip()

    missing = [
        name
        for name, val in [
            ("OPENCODE_MODEL_ID", model_id),
            ("OPENCODE_PROVIDER_ID", provider_id),
        ]
        if not val
    ]
    if missing:
        print(f"ERROR: missing env vars: {', '.join(missing)}")
        sys.exit(1)

    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "请输出你的工作目录，你当前可用的skills，以及mcp tools"

    print(f"[config] base_url={base_url} session={session_id or '(will create new)'} model={model_id}")
    print(f"[input]  {text!r}")
    print()

    client = OpenCodeClient(
        base_url=base_url,
        session_id=session_id,
        model_id=model_id,
        provider_id=provider_id,
    )
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
