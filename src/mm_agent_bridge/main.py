"""Entry point for mm-agent-bridge."""

from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

from .config import Config
from .bot import AgentBridge


def main() -> None:
    """Load configuration and start the bot."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    load_dotenv()

    try:
        config = Config.from_env()
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    logger.info("Starting mm-agent-bridge (agent=%s)", config.agent_type)
    bot = AgentBridge(config=config)
    bot.run()


if __name__ == "__main__":
    main()
